"""
RAG Evaluation Module
Evaluates RAG pipeline quality using multiple metrics
"""
import requests
import time
from typing import Dict, List, Any
import chromadb
from chromadb.config import Settings


class RAGEvaluator:
    """Evaluate RAG pipeline performance"""
    
    def __init__(
        self,
        vector_db_endpoint: str,
        ollama_endpoint: str,
        collection_name: str = "documents"
    ):
        self.vector_db_endpoint = vector_db_endpoint
        self.ollama_endpoint = ollama_endpoint
        
        # Connect to ChromaDB
        host = vector_db_endpoint.split('//')[1].split(':')[0]
        port = int(vector_db_endpoint.split(':')[-1].split('/')[0])
        
        self.client = chromadb.HttpClient(
            host=host,
            port=port,
            settings=Settings(anonymized_telemetry=False)
        )
        
        self.collection = self.client.get_collection(name=collection_name)
    
    def retrieve_context(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve relevant context from vector DB"""
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k
        )
        
        contexts = []
        for i in range(len(results['documents'][0])):
            contexts.append({
                'text': results['documents'][0][i],
                'metadata': results['metadatas'][0][i],
                'distance': results['distances'][0][i]
            })
        
        return contexts
    
    def generate_response(self, query: str, context: str) -> str:
        """Generate response using Ollama"""
        prompt = f"""Context: {context}

Question: {query}

Answer the question based only on the provided context. If the context doesn't contain relevant information, say so."""
        
        response = requests.post(
            f"{self.ollama_endpoint}/api/generate",
            json={
                "model": "llama2",
                "prompt": prompt,
                "stream": False
            }
        )
        
        return response.json()['response']
    
    def evaluate_query(self, query: str) -> Dict[str, float]:
        """Evaluate a single query through the RAG pipeline"""
        start_time = time.time()
        
        # Retrieve context
        contexts = self.retrieve_context(query)
        context_text = "\n\n".join([c['text'] for c in contexts])
        
        # Generate response
        response = self.generate_response(query, context_text)
        
        response_time = time.time() - start_time
        
        # Calculate metrics
        faithfulness = self._calculate_faithfulness(response, context_text)
        relevance = self._calculate_relevance(query, contexts)
        coherence = self._calculate_coherence(response)
        
        return {
            'query': query,
            'response': response,
            'contexts': contexts,
            'faithfulness': faithfulness,
            'relevance': relevance,
            'coherence': coherence,
            'response_time': response_time
        }
    
    def _calculate_faithfulness(self, response: str, context: str) -> float:
        """
        Calculate faithfulness score (how well response is grounded in context)
        Simplified version - in production use more sophisticated methods
        """
        # Check if key phrases from response appear in context
        response_words = set(response.lower().split())
        context_words = set(context.lower().split())
        
        overlap = len(response_words.intersection(context_words))
        faithfulness = overlap / len(response_words) if response_words else 0.0
        
        return min(faithfulness, 1.0)
    
    def _calculate_relevance(self, query: str, contexts: List[Dict]) -> float:
        """Calculate relevance of retrieved contexts"""
        if not contexts:
            return 0.0
        
        # Use distance scores from vector DB
        avg_distance = sum(c['distance'] for c in contexts) / len(contexts)
        
        # Convert distance to similarity (assuming cosine distance)
        relevance = 1 - avg_distance
        
        return max(0.0, min(relevance, 1.0))
    
    def _calculate_coherence(self, response: str) -> float:
        """
        Calculate coherence of response
        Simplified version - checks for complete sentences
        """
        sentences = response.split('.')
        complete_sentences = [s for s in sentences if len(s.strip()) > 10]
        
        if not sentences:
            return 0.0
        
        coherence = len(complete_sentences) / len(sentences)
        return coherence
    
    def batch_evaluate(
        self,
        queries: List[str]
    ) -> Dict[str, Any]:
        """Evaluate multiple queries and aggregate results"""
        results = []
        
        for query in queries:
            result = self.evaluate_query(query)
            results.append(result)
        
        # Aggregate metrics
        avg_metrics = {
            'avg_faithfulness': sum(r['faithfulness'] for r in results) / len(results),
            'avg_relevance': sum(r['relevance'] for r in results) / len(results),
            'avg_coherence': sum(r['coherence'] for r in results) / len(results),
            'avg_response_time': sum(r['response_time'] for r in results) / len(results),
            'total_queries': len(results)
        }
        
        return {
            'individual_results': results,
            'aggregate_metrics': avg_metrics
        }