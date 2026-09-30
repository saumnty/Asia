import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.rag.indexer import ProjectIndexer
from core.rag.retriever import ProjectRetriever


def print_results(results):
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    if not documents:
        print("No se encontraron resultados.")
        return

    for i, (doc, metadata, distance) in enumerate(
        zip(documents, metadatas, distances),
        start=1
    ):
        file_path = metadata.get("file_path", "archivo desconocido")
        chunk = metadata.get("chunk", "?")

        preview = doc.strip().replace("\n", " ")
        preview = preview[:500]

        print(f"\n{i}. Archivo: {file_path}")
        print(f"   Chunk: {chunk}")
        print(f"   Distancia: {distance}")
        print(f"   Preview: {preview}...")


def main():
    print("=== TEST RAG ===")

    project_path = "."

    print("Indexando proyecto...")
    indexer = ProjectIndexer(
        project_path=".",
        project_name="asia"
    )

    count = indexer.index_project()

    print(f"\nDocumentos indexados: {count}")

    question = "donde se maneja el provider de gemini"

    print(f"\nPregunta: {question}")
    print("\nBuscando...")

    retriever = ProjectRetriever(
        project_name="asia"
    )
    results = retriever.search(question)

    print("\nRESULTADOS:")
    print_results(results)


if __name__ == "__main__":
    main()