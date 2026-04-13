output "project_id" {
  value = var.project_id
}

output "cluster_name" {
  value = google_container_cluster.resilientp2p.name
}

output "cluster_location" {
  value = google_container_cluster.resilientp2p.location
}

output "artifact_registry_repo" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker_repo.repository_id}"
}

output "results_bucket_url" {
  value = "gs://${google_storage_bucket.results.name}"
}

output "get_credentials_command" {
  value = "gcloud container clusters get-credentials ${google_container_cluster.resilientp2p.name} --zone ${google_container_cluster.resilientp2p.location} --project ${var.project_id}"
}

