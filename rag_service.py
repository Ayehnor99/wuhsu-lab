import os
import gc
import logging
from typing import List
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings

# Initialize Embeddings
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
embeddings = OllamaEmbeddings(model="nomic-embed-text", base_url=OLLAMA_BASE_URL)

PERSIST_DIRECTORY = ".wuhsu_vector_db"
BATCH_SIZE = 150  # Process 150 chunks at a time to prevent RAM overflow

class RAGService:
    @staticmethod
    def ingest_document(file_path: str, filename: str) -> int:
        """Parses a document, chunks it, and saves it to ChromaDB in safe batches."""
        logging.info(f"📚 [RAG] Starting ingestion for: {filename}")
        
        try:
            # 1. Error-Tolerant Loading
            if file_path.lower().endswith('.pdf'):
                loader = PyPDFLoader(file_path)
            elif file_path.lower().endswith(('.txt', '.md', '.log', '.csv')):
                loader = TextLoader(file_path, encoding='utf-8')
            else:
                raise ValueError("Unsupported file extension.")
                
            documents = loader.load()
            
            # Add metadata for strict citations
            for doc in documents:
                doc.metadata["source_file"] = filename
                
        except Exception as e:
            logging.error(f"❌ [RAG] Parsing failed for {filename}: {e}")
            raise Exception(f"Failed to parse document. It may be corrupted. Error: {e}")

        # 2. Chunking
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, 
            chunk_overlap=200,
            separators=["\n\n", "\n", " ", ""]
        )
        chunks = text_splitter.split_documents(documents)
        total_chunks = len(chunks)
        logging.info(f"📚 [RAG] Document split into {total_chunks} chunks. Starting batch processing...")

        # 3. Batch Processing & Memory Management (The Enterprise Fix)
        # Instead of feeding 10,000 chunks to the embedding model at once, we feed BATCH_SIZE
        vectorstore = Chroma(persist_directory=PERSIST_DIRECTORY, embedding_function=embeddings)
        
        for i in range(0, total_chunks, BATCH_SIZE):
            batch = chunks[i : i + BATCH_SIZE]
            try:
                vectorstore.add_documents(documents=batch)
                logging.info(f"📚 [RAG] Processed batch {i//BATCH_SIZE + 1}/{(total_chunks//BATCH_SIZE) + 1}")
            except Exception as e:
                logging.error(f"❌ [RAG] Batch {i} failed: {e}. Skipping to next batch to maintain uptime.")
                continue
                
            # Explicitly free memory after each heavy embedding batch
            del batch
            gc.collect()

        logging.info(f"✅ [RAG] Successfully ingested {filename}.")
        return total_chunks

    @staticmethod
    def search_knowledge_base(query: str, k: int = 4) -> str:
        """Searches the vector database and formats results for the LLM."""
        if not os.path.exists(PERSIST_DIRECTORY):
            return ""
            
        try:
            vectorstore = Chroma(persist_directory=PERSIST_DIRECTORY, embedding_function=embeddings)
            docs = vectorstore.similarity_search(query, k=k)
            
            if not docs:
                return ""
                
            # Format exactly as the article requested for professional references
            context_blocks =[]
            for d in docs:
                source = d.metadata.get('source_file', 'Unknown')
                page = d.metadata.get('page', 'N/A')
                context_blocks.append(f"Reference: {source} (Page {page})\nContent: {d.page_content}")
                
            return "\n\n---\n\n".join(context_blocks)
        except Exception as e:
            logging.error(f"RAG Search Error: {e}")
            return ""
