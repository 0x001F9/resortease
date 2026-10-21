from pathlib import Path
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.vectorstores import InMemoryVectorStore

# Load and split md
md_split = MarkdownHeaderTextSplitter(
    headers_to_split_on=[
        ("#", "h1"),
        ("##", "h2"),
        ("###", "h3")
    ]
)
size_split = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)

chunks = []
for md_path in Path("agent_chat/rag/docs").rglob("*.md"):
    for doc in md_split.split_text(md_path.read_text(encoding="utf-8")):
        doc.metadata["source"] = str(md_path)
        chunks.extend(size_split.split_documents([doc]))

vec_store = InMemoryVectorStore(
    GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        task_type="retrieval_document"   
    )
)
vec_store.add_documents(chunks)

from langchain.tools import tool

@tool(response_format="content_and_artifact")
def search_docs(query: str):
    """Search the mrkdown docs for information"""
    docs = vec_store.similarity_search(query)
    text = "\n\n".join(
        f"[{d.metadata['spurce']}]\n{d.page_content}" for d in docs
    )

    return text, docs