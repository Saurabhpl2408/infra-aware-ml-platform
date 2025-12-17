
resource "kubernetes_namespace" "storage" {
  metadata {
    name = var.namespace
  }
}

resource "kubernetes_persistent_volume_claim" "minio_pvc" {
  metadata {
    name      = "minio-pvc"
    namespace = var.namespace
  }
  
  spec {
    access_modes = ["ReadWriteOnce"]
    resources {
      requests = {
        storage = "${var.storage_size_gb}Gi"
      }
    }
  }
  
  depends_on = [kubernetes_namespace.storage]
}

resource "kubernetes_deployment" "minio" {
  metadata {
    name      = "minio"
    namespace = var.namespace
    labels = {
      app = "minio"
    }
  }
  
  spec {
    replicas = 1
    
    selector {
      match_labels = {
        app = "minio"
      }
    }
    
    template {
      metadata {
        labels = {
          app = "minio"
        }
      }
      
      spec {
        container {
          name  = "minio"
          image = "minio/minio:latest"
          
          args = ["server", "/data", "--console-address", ":9001"]
          
          env {
            name  = "MINIO_ROOT_USER"
            value = var.access_key
          }
          
          env {
            name  = "MINIO_ROOT_PASSWORD"
            value = var.secret_key
          }
          
          port {
            container_port = 9000
            name          = "api"
          }
          
          port {
            container_port = 9001
            name          = "console"
          }
          
          volume_mount {
            name       = "storage"
            mount_path = "/data"
          }
          
          resources {
            requests = {
              cpu    = "500m"
              memory = "1Gi"
            }
            limits = {
              cpu    = "1000m"
              memory = "2Gi"
            }
          }
        }
        
        volume {
          name = "storage"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim.minio_pvc.metadata[0].name
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "minio" {
  metadata {
    name      = "minio"
    namespace = var.namespace
  }
  
  spec {
    selector = {
      app = "minio"
    }
    
    port {
      name        = "api"
      port        = 9000
      target_port = 9000
      node_port   = 30003
    }
    
    port {
      name        = "console"
      port        = 9001
      target_port = 9001
    }
    
    type = "NodePort"
  }
}

resource "kubernetes_job" "create_buckets" {
  metadata {
    name      = "minio-bucket-init"
    namespace = var.namespace
  }
  
  spec {
    template {
      metadata {
        labels = {
          app = "minio-init"
        }
      }
      
      spec {
        restart_policy = "OnFailure"
        
        container {
          name  = "mc"
          image = "minio/mc:latest"
          
          command = ["/bin/sh", "-c"]
          args = [<<-EOT
            mc alias set minio http://minio:9000 ${var.access_key} ${var.secret_key}
            ${join("\n", [for bucket in var.bucket_names : "mc mb --ignore-existing minio/${bucket}"])}
            echo "Buckets created successfully"
          EOT
          ]
        }
      }
    }
  }
  
  depends_on = [kubernetes_service.minio]
}