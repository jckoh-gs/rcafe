terraform {
  backend "s3" {
    bucket       = "__STATE_BUCKET__"
    key          = "__ENV__/__COMPONENT__/terraform.tfstate"
    region       = "__STATE_REGION__"
    encrypt      = true
    use_lockfile = true
  }
}
