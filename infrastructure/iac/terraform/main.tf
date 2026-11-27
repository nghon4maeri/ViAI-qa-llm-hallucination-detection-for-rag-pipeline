# infrastructure/iac/terraform/main.tf
terraform {
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.25"
    }
  }
}

# Local cluster only (`deployctl up`, infrastructure/k8s/deployctl, creates the viai-qa profile).
# Pass -var kube_context=... for another local cluster; GKE is provisioned from ./gke.
variable "kube_context" {
  type    = string
  default = "viai-qa"
}

provider "kubernetes" {
  config_path    = "~/.kube/config"
  config_context = var.kube_context
}

variable "ghcr_username" {
  type      = string
  sensitive = true
}

variable "ghcr_token" {
  type      = string
  sensitive = true
}

locals {
  dockerconfigjson = jsonencode({
    auths = {
      "ghcr.io" = {
        username = var.ghcr_username
        password = var.ghcr_token
        auth     = base64encode("${var.ghcr_username}:${var.ghcr_token}")
      }
    }
  })
}

resource "kubernetes_secret" "ghcr" {
  metadata {
    name      = "ghcr-secret"
    namespace = "hallucination-prod"
  }

  type = "kubernetes.io/dockerconfigjson"

  data = {
    ".dockerconfigjson" = jsonencode({
      auths = {
        "ghcr.io" = {
          username = var.ghcr_username
          password = var.ghcr_token
          auth     = base64encode("${var.ghcr_username}:${var.ghcr_token}")
        }
      }
    })
  }
}
