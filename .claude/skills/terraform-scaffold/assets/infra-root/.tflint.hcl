# Lints every module and composition under this directory (tflint --chdir=<dir> --config=<this file>).
plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.49.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}

# terraform-best-practices.com conventions, enforced mechanically.
rule "terraform_naming_convention" {
  enabled = true # snake_case identifiers
}

rule "terraform_documented_variables" {
  enabled = true
}

rule "terraform_documented_outputs" {
  enabled = true
}

rule "terraform_standard_module_structure" {
  enabled = true # variables in variables.tf, outputs in outputs.tf
}

rule "terraform_comment_syntax" {
  enabled = true # '#' comments only
}

rule "terraform_unused_required_providers" {
  enabled = true
}
