
resource "kubernetes_namespace" "vector_db" {
  metadata {
    name = var.namespace
  }
}

resource "kubernetes_persistent_volume_claim" "chroma_pvc" {
  metadata {
    name      = "chroma-pvc"
    namespace = var.namespace
  }
  
  spec {
    access_modes = ["ReadWriteOnce"]
    resources {
      requests = {
        storage = var.persistence_size
      }
    }
  }
  
  depends_on = [kubernetes_namespace.vector_db]
}

resource "kubernetes_deployment" "chroma" {
  metadata {
    name      = "chromadb"
    namespace = var.namespace
    labels = {
      app = "chromadb"
    }
  }
  
  spec {
    replicas = var.replicas
    
    selector {
      match_labels = {
        app = "chromadb"
      }
    }
    
    template {
      metadata {
        labels = {
          app = "chromadb"
        }
      }
      
      spec {
        container {
          name  = "chromadb"
          image = "ghcr.io/chroma-core/chroma:latest"
          
          env {
            name  = "IS_PERSISTENT"
            value = "TRUE"
          }
          
          env {
            name  = "PERSIST_DIRECTORY"
            value = "/chroma/data"
          }
          
          env {
            name  = "ANONYMIZED_TELEMETRY"
            value = "FALSE"
          }
          
          port {
            container_port = 8000
            name          = "http"
          }
          
          volume_mount {
            name       = "chroma-data"
            mount_path = "/chroma/data"
          }
          
          resources {
            requests = {
              cpu    = "500m"
              memory = "1Gi"
            }
            limits = {
              cpu    = "2000m"
              memory = "4Gi"
            }
          }
          
          liveness_probe {
            http_get {
              path = "/api/v1/heartbeat"
              port = 8000
            }
            initial_delay_seconds = 30
            period_seconds        = 10
          }
        }
        
        volume {
          name = "chroma-data"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim.chroma_pvc.metadata[0].name
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "chroma" {
  metadata {
    name      = "chromadb"
    namespace = var.namespace
  }
  
  spec {
    selector = {
      app = "chromadb"
    }
    
    port {
      port        = 8000
      target_port = 8000
      node_port   = 30004
    }
    
    type = "NodePort"
  }
}