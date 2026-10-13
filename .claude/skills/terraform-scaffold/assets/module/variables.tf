variable "name" {
  description = "Name used for the module's resources."
  type        = string
  nullable    = false
}

variable "tags" {
  description = "Additional tags for all resources. Environment-wide tags come from the provider's default_tags."
  type        = map(string)
  default     = {}
}
