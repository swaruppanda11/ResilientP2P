variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "Primary GCP region"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Primary GCP zone for the GKE cluster"
  type        = string
  default     = "us-central1-f"
}

variable "cluster_name" {
  description = "GKE cluster name"
  type        = string
  default     = "resilientp2p-gke"
}

variable "artifact_registry_repo" {
  description = "Artifact Registry repository name"
  type        = string
  default     = "resilientp2p"
}

variable "results_bucket_name" {
  description = "GCS bucket name for experiment artifacts"
  type        = string
  default     = "resilientp2p-results"
}

variable "cluster_machine_type" {
  description = "Machine type for node pools"
  type        = string
  default     = "e2-medium"
}

variable "building_a_node_count" {
  description = "Node count for building-a-pool"
  type        = number
  default     = 1
}

variable "building_b_node_count" {
  description = "Node count for building-b-pool"
  type        = number
  default     = 1
}

