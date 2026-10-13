output "s3_bucket_id" {
  description = "Name of the bucket the build is uploaded to (S3_BUCKET for deploy-frontend)."
  value       = aws_s3_bucket.this.id
}

output "s3_bucket_arn" {
  description = "ARN of the bucket, for granting deploy permissions."
  value       = aws_s3_bucket.this.arn
}

output "cloudfront_distribution_id" {
  description = "ID of the distribution (CLOUDFRONT_DISTRIBUTION_ID for deploy-frontend)."
  value       = aws_cloudfront_distribution.this.id
}

output "cloudfront_distribution_arn" {
  description = "ARN of the distribution, for granting invalidation permissions."
  value       = aws_cloudfront_distribution.this.arn
}

output "cloudfront_distribution_domain_name" {
  description = "*.cloudfront.net domain of the distribution, the target for DNS aliases."
  value       = aws_cloudfront_distribution.this.domain_name
}

output "cloudfront_distribution_hosted_zone_id" {
  description = "Route 53 hosted zone ID to use in alias records pointing at the distribution."
  value       = aws_cloudfront_distribution.this.hosted_zone_id
}
