"""
Embedding Generator using sentence-transformers
Infrastructure-aware batching and resource utilization
"""
import os
import torch
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any
import numpy as np
from tqdm import tqdm


class EmbeddingGenerator:
    """Generate embeddings with dynamic batch sizing based on infrastructure"""
    
    def __init__(
        self,
        model_name: str = 'all-MiniLM-L6-v2',
        batch_size: int = 32,
        device: str = None
    ):
        self.model_name = model_name
        self.batch_size = batch_size
        
        # Auto-detect device
        if device is None:
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        else:
            self.device = device
        
        # Load model
        self.model = SentenceTransformer(model_name)
        self.model.to(self.device)
        
        print(f"Loaded {model_name} on {self.device}")
        print(f"Embedding dimension: {self.model.get_sentence_embedding_dimension()}")
    
    def generate_embeddings(
        self,
        texts: List[str],
        show_progress: bool = True
    ) -> np.ndarray:
        """
        Generate embeddings for a list of texts
        
        Args:
            texts: List of text strings
            show_progress: Show progress bar
        
        Returns:
            numpy array of embeddings
        """
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
            device=self.device
        )
        
        return embeddings
    
    def generate_batch_with_metadata(
        self,
        documents: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Generate embeddings with metadata
        
        Args:
            documents: List of dicts with 'text' and 'metadata' keys
        
        Returns:
            List of dicts with embeddings added
        """
        texts = [doc['text'] for doc in documents]
        embeddings = self.generate_embeddings(texts)
        
        results = []
        for doc, embedding in zip(documents, embeddings):
            results.append({
                'id': doc.get('id', f"doc_{hash(doc['text'])}"),
                'text': doc['text'],
                'embedding': embedding.tolist(),
                'metadata': doc.get('metadata', {}),
                'model': self.model_name,
                'dimension': len(embedding)
            })
        
        return results
    
    def calculate_similarity(
        self,
        query_embedding: np.ndarray,
        document_embeddings: np.ndarray
    ) -> np.ndarray:
        """Calculate cosine similarity between query and documents"""
        from sklearn.metrics.pairwise import cosine_similarity
        
        return cosine_similarity(
            query_embedding.reshape(1, -1),
            document_embeddings
        )[0]


if __name__ == '__main__':
    # CLI for batch processing
    import argparse
    import pickle
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-file', required=True)
    parser.add_argument('--output-file', required=True)
    parser.add_argument('--model-name', default='all-MiniLM-L6-v2')
    parser.add_argument('--batch-size', type=int, default=32)
    
    args = parser.parse_args()
    
    # Load documents
    with open(args.input_file, 'rb') as f:
        documents = pickle.load(f)
    
    # Generate embeddings
    generator = EmbeddingGenerator(
        model_name=args.model_name,
        batch_size=args.batch_size
    )
    
    results = generator.generate_batch_with_metadata(documents)
    
    # Save results
    with open(args.output_file, 'wb') as f:
        pickle.dump(results, f)
    
    print(f"Generated {len(results)} embeddings")