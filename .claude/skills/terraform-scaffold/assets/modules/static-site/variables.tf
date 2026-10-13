variable "bucket_name" {
  description = "Globally unique name of the S3 bucket that stores the build."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "bucket_name must be a valid S3 bucket name."
  }
}

variable "aliases" {
  description = "Custom domain names for the distribution. Requires acm_certificate_arn."
  type        = list(string)
  default     = []
  nullable    = false
}

variable "acm_certificate_arn" {
  description = "ARN of an ACM certificate in us-east-1 covering the aliases. Null uses the default *.cloudfront.net certificate."
  type        = string
  default     = null

  validation {
    condition     = var.acm_certificate_arn == null || startswith(coalesce(var.acm_certificate_arn, "-"), "arn:aws:acm:us-east-1:")
    error_message = "CloudFront requires the ACM certificate to be in us-east-1."
  }
}

variable "price_class" {
  description = "CloudFront price class."
  type        = string
  default     = "PriceClass_100"

  validation {
    condition     = contains(["PriceClass_100", "PriceClass_200", "PriceClass_All"], var.price_class)
    error_message = "price_class must be PriceClass_100, PriceClass_200 or PriceClass_All."
  }
}

variable "spa_fallback_enabled" {
  description = "Serve /index.html for unknown paths so client-side routing works."
  type        = bool
  default     = true
  nullable    = false
}

variable "versioning_enabled" {
  description = "Keep previous object versions in the bucket."
  type        = bool
  default     = false
  nullable    = false
}

variable "force_destroy" {
  description = "Allow destroying the bucket while it still contains objects."
  type        = bool
  default     = false
  nullable    = false
}

variable "comment" {
  description = "Comment shown on the CloudFront distribution."
  type        = string
  default     = null
}

variable "tags" {
  description = "Additional tags for all resources. Environment-wide tags come from the provider's default_tags."
  type        = map(string)
  default     = {}
  nullable    = false
}
