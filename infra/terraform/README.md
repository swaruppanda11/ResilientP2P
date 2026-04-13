# ResilientP2P Terraform (Phase 10)

This directory provisions the Phase 10 baseline infrastructure:

- GKE cluster (`resilientp2p-gke` by default)
- two node pools with labels used by current manifests (`building=a`, `building=b`)
- Artifact Registry Docker repo
- GCS bucket for results
- required APIs (`container`, `artifactregistry`, `storage`)

## 1) Prerequisites

- Terraform `>= 1.6`
- `gcloud` authenticated with the target project
- IAM permissions to create GKE, Artifact Registry, and GCS resources

## 2) Configure

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` if needed.

## 3) Apply

```bash
terraform init
terraform plan
terraform apply
```

After apply, use:

```bash
terraform output get_credentials_command
```

and run the printed command to configure `kubectl`.

## 4) Phase 10 experiment workflow

From repo root:

```bash
./scripts/run-k8s-suite.sh 5
./scripts/run-k8s-suite.sh 5 --vary-seed
python3 scripts/aggregate-results.py
python3 scripts/plot-results.py
./scripts/export-to-gcs.sh
```

## 5) Destroy (when done)

```bash
terraform destroy
```

Note: `google_storage_bucket.results` uses `force_destroy = false`.
Empty bucket objects before destroy if needed.

