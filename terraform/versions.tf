terraform {
  required_version = "~> 1.9"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 9.0"
    }
    # レンダリング結果を ansible/files/ へ書き出すために使う (render.tf)
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}

provider "oci" {
  region = var.region
}
