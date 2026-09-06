import os
from chromadb import Documents, EmbeddingFunction, Embeddings
from google import genai
from google.genai import types

class GeminiEmbeddingFunction(EmbeddingFunction):
    def __init__(self, api_key: str = None, model_name: str = "gemini-embedding-2"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")
        
        # Initialize the modern genai client
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = model_name

    def __call__(self, input: Documents) -> Embeddings:
        # Wrap each chunk in Content/Part to ensure the SDK batches them correctly
        # instead of merging them into a single embedding
        contents = [types.Content(parts=[types.Part(text=t)]) for t in input]
        
        # Generate embeddings for the list of text chunks
        response = self.client.models.embed_content(
            model=self.model_name,
            contents=contents,
        )
        
        # Extract the float arrays from the response objects
        return [e.values for e in response.embeddings]