import os
from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(
    model=os.getenv("GEMINI_API_KEY", "gemini-1.5-flash"),
    api_key=os.getenv("GEMINI_API_KEY")
)