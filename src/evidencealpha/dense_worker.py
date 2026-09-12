"""Explicit offline E5 embedding worker; no implicit model downloads."""

import hashlib
import pathlib
import sys
import time

from evidencealpha import artifacts
from evidencealpha import documents
from evidencealpha import embedding_chunks
from evidencealpha import preparation
from evidencealpha import vector_index


def model_signature(path: pathlib.Path, revision: str) -> dict:
    """Hash exact local model/tokenizer artifacts used by this encoder."""
    files = {}
    for name in (
        "config.json",
        "model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
    ):
        with (path / name).open("rb") as stream:
            files[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "model": "intfloat/multilingual-e5-base",
        "revision": revision,
        "dimension": 768,
        "input_policy": embedding_chunks.VERSION,
        "normalization": "l2",
        "pooling": "attention-mask-mean",
        "prefixes": ["query: ", "passage: "],
        "files": files,
    }


def execute(request: dict) -> dict:
    """Perform one build or query under the caller's process supervisor."""
    import torch  # pylint: disable=import-outside-toplevel
    import transformers  # pylint: disable=import-outside-toplevel

    torch.set_num_threads(request["settings"]["reranker_threads"])
    settings = request["settings"]
    path = pathlib.Path(settings["dense_model_path"])
    metrics = {}
    start = time.monotonic()
    signature = model_signature(path, settings["dense_model_revision"])
    signature["unit_tokens"] = settings["embedding_unit_tokens"]
    metrics["snapshot_seconds"] = time.monotonic() - start
    start = time.monotonic()
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        path, local_files_only=True, trust_remote_code=False
    )
    if tokenizer.model_max_length < 512:
        raise ValueError("Unexpected E5 tokenizer capacity")
    model = transformers.AutoModel.from_pretrained(
        path,
        local_files_only=True,
        trust_remote_code=False,
        torch_dtype=torch.float32,
    ).eval()
    if model.config.hidden_size != 768:
        raise ValueError("Unexpected embedding model dimension")
    metrics["initialization_seconds"] = time.monotonic() - start

    def encode(texts):
        encoded = tokenizer(
            texts, padding=True, truncation=False, return_tensors="pt"
        )
        if encoded["input_ids"].shape[1] > 512:
            raise ValueError(
                "Embedding input exceeds verified 512-token capacity"
            )
        with torch.inference_mode():
            outputs = model(**encoded).last_hidden_state
            masked = outputs.masked_fill(
                ~encoded["attention_mask"][..., None].bool(), 0.0
            )
            means = (
                masked.sum(dim=1)
                / encoded["attention_mask"].sum(dim=1)[..., None]
            )
            return torch.nn.functional.normalize(means, p=2, dim=1).tolist()

    store = documents.SourceStore(pathlib.Path(request["corpus"]))
    if request["operation"] == "build":
        start = time.monotonic()
        units = embedding_chunks.build_units(
            store,
            lambda text: len(
                tokenizer.encode("passage: " + text, truncation=False)
            ),
            settings["embedding_unit_tokens"],
            preparation.noop,
        )
        metrics["chunking_seconds"] = time.monotonic() - start
        vectors = {}
        ids = sorted(units)
        start = time.monotonic()
        for i in range(0, len(ids), 8):
            batch = ids[i : i + 8]
            values = encode(
                [
                    "passage: " + embedding_chunks.text_for(store, units[k])
                    for k in batch
                ]
            )
            vectors.update(zip(batch, values))
        metrics["embedding_seconds"] = time.monotonic() - start
        start = time.monotonic()
        manifest = vector_index.ReferenceIndex.build(
            pathlib.Path(request["output"]), store, signature, vectors, units
        )
        metrics["indexing_seconds"] = time.monotonic() - start
        metrics.update(
            units=len(units),
            fallback_splits=sum(u["fallback_split"] for u in units.values()),
        )
        return {"manifest": manifest, "metrics": metrics}
    start = time.monotonic()
    embedding = encode(["query: " + request["query"]])[0]
    metrics["query_embedding_seconds"] = time.monotonic() - start
    start = time.monotonic()
    index = vector_index.ReferenceIndex(
        pathlib.Path(settings["vector_index_path"]), store, signature
    )
    metrics["index_open_validation_seconds"] = time.monotonic() - start
    start = time.monotonic()
    hits = index.query(embedding, request["source_id"], request["limit"])
    metrics["vector_query_seconds"] = time.monotonic() - start
    return {
        "hits": [
            {
                "source_id": h["passage"]["source_id"],
                "chunk_id": h["passage"]["chunk_id"],
                "distance": h["dense_distance"],
                "unit": h["embedding_unit"],
                "unit_id": h["unit_id"],
            }
            for h in hits
        ],
        "metrics": metrics,
        "index_hash": artifacts.digest(index.manifest),
    }


if __name__ == "__main__":
    request_path = pathlib.Path(sys.argv[1])
    artifacts.write(
        request_path.parent / "response.json",
        execute(artifacts.read(request_path)),
    )
