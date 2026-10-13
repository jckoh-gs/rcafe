variable "environment" {
  description = "Environment name, e.g. dev, stage, prod."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*$", var.environment))
    error_message = "environment must be lowercase letters, digits and dashes."
  }
}

variable "region" {
  description = "AWS region for this composition's resources."
  type        = string
  nullable    = false
}

variable "aws_account_id" {
  description = "AWS account this environment lives in. Terraform refuses to run against any other account."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be a 12-digit AWS account ID."
  }
}
