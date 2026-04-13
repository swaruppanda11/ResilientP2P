provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

locals {
  required_apis = toset([
    "container.googleapis.com",
    "artifactregistry.googleapis.com",
    "storage.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each = locals.required_apis
  project  = var.project_id
  service  = each.value

  disable_dependent_services = false
  disable_on_destroy         = false
}

resource "google_artifact_registry_repository" "docker_repo" {
  location      = var.region
  repository_id = var.artifact_registry_repo
  description   = "Docker repository for ResilientP2P images"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "results" {
  name                        = var.results_bucket_name
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true

  depends_on = [google_project_service.required]
}

resource "google_container_cluster" "resilientp2p" {
  name     = var.cluster_name
  location = var.zone

  # Use custom node pools to keep deterministic labels used by k8s manifests.
  remove_default_node_pool = true
  initial_node_count       = 1

  deletion_protection = false

  depends_on = [google_project_service.required]
}

resource "google_container_node_pool" "building_a" {
  name       = "building-a-pool"
  location   = var.zone
  cluster    = google_container_cluster.resilientp2p.name
  node_count = var.building_a_node_count

  node_config {
    machine_type = var.cluster_machine_type
    labels = {
      building = "a"
    }
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
}

resource "google_container_node_pool" "building_b" {
  name       = "building-b-pool"
  location   = var.zone
  cluster    = google_container_cluster.resilientp2p.name
  node_count = var.building_b_node_count

  node_config {
    machine_type = var.cluster_machine_type
    labels = {
      building = "b"
    }
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
}

