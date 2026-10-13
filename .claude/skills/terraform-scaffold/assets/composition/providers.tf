provider "aws" {
  region              = var.region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Environment = var.environment
      Component   = "__COMPONENT__"
      ManagedBy   = "terraform"
    }
  }
}
