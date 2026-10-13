# __MODULE__

What this module creates and why.

## Usage

```hcl
module "__MODULE_SNAKE__" {
  source = "../../../modules/__MODULE__"

  name = "prod-example"
}
```

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| name | Name used for the module's resources. | `string` | n/a |
| tags | Additional tags for all resources. | `map(string)` | `{}` |

## Outputs

| Name | Description |
|---|---|
