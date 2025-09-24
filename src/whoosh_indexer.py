from whoosh.index import create_in, open_dir
from whoosh.fields import Schema, TEXT, ID
from whoosh.qparser import MultifieldParser
import os
import shutil

# This script builds a Whoosh index for all document chunks (from Chroma or your pipeline)
# and provides a function to run BM25 keyword search on them.

INDEX_DIR = "output/whoosh_index"

schema = Schema(
    chunk_id=ID(stored=True, unique=True),
    content=TEXT(stored=True),
    subject=TEXT(stored=True),
    policy_no=ID(stored=True),
    date=ID(stored=True),
    pdf_filename=ID(stored=True),
)

def build_whoosh_index(docs):
    if os.path.exists(INDEX_DIR):
        shutil.rmtree(INDEX_DIR)
    os.makedirs(INDEX_DIR, exist_ok=True)
    ix = create_in(INDEX_DIR, schema)
    writer = ix.writer()
    for doc in docs:
        writer.add_document(
            chunk_id=doc.metadata.get('chunk_id', ''),
            content=doc.page_content,
            subject=doc.metadata.get('subject', ''),
            policy_no=doc.metadata.get('policy_no', ''),
            date=doc.metadata.get('date', ''),
            pdf_filename=doc.metadata.get('pdf_filename', ''),
        )
    writer.commit()
    print(f"Whoosh index built with {len(docs)} chunks.")

def bm25_search(query, top_k=5):
    ix = open_dir(INDEX_DIR)
    with ix.searcher() as searcher:
        parser = MultifieldParser(["content", "subject"], schema=ix.schema)
        q = parser.parse(query)
        results = searcher.search(q, limit=top_k)
        return [dict(r) for r in results]
