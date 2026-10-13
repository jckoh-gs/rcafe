# static-site

Hosts a static frontend build: a private S3 bucket served only through CloudFront with Origin Access Control.
The bucket has Block Public Access fully enabled and no public policy; the bucket policy allows `s3:GetObject`
only for this distribution. This is exactly what the `deploy-frontend` skill checks before deploying.

Unknown paths return `/index.html` (SPA routing) unless `spa_fallback_enabled = false`.

## Usage

```hcl
module "static_site" {
  source = "../../../modules/static-site"

  bucket_name = "prod-web-frontend-123456789012"

  # Optional custom domain (certificate must be in us-east-1):
  # aliases             = ["www.example.com"]
  # acm_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/..."
}
```

Map the outputs to the frontend's `.deploy/<env>.env`:

| Output | deploy-frontend variable |
|---|---|
| `s3_bucket_id` | `S3_BUCKET` |
| `cloudfront_distribution_id` | `CLOUDFRONT_DISTRIBUTION_ID` |

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| bucket_name | Globally unique name of the S3 bucket that stores the build. | `string` | n/a |
| aliases | Custom domain names for the distribution. Requires `acm_certificate_arn`. | `list(string)` | `[]` |
| acm_certificate_arn | ACM certificate in us-east-1 covering the aliases. Null uses the default certificate. | `string` | `null` |
| price_class | CloudFront price class. | `string` | `"PriceClass_100"` |
| spa_fallback_enabled | Serve `/index.html` for unknown paths. | `bool` | `true` |
| versioning_enabled | Keep previous object versions in the bucket. | `bool` | `false` |
| force_destroy | Allow destroying the bucket while it still contains objects. | `bool` | `false` |
| comment | Comment shown on the distribution. | `string` | `null` |
| tags | Additional tags for all resources. | `map(string)` | `{}` |

## Outputs

| Name | Description |
|---|---|
| s3_bucket_id | Bucket name (`S3_BUCKET`). |
| s3_bucket_arn | Bucket ARN, for deploy permissions. |
| cloudfront_distribution_id | Distribution ID (`CLOUDFRONT_DISTRIBUTION_ID`). |
| cloudfront_distribution_arn | Distribution ARN, for invalidation permissions. |
| cloudfront_distribution_domain_name | `*.cloudfront.net` domain, the DNS alias target. |
| cloudfront_distribution_hosted_zone_id | Hosted zone ID for Route 53 alias records. |
