import { defineConfig } from 'steiger'
import fsd from '@feature-sliced/steiger-plugin'

// Enforces FSD layer direction, cross-slice import bans and public APIs.
export default defineConfig([
  ...fsd.configs.recommended,
  {
    // Too noisy while a project is small; re-enable once slices settle.
    rules: {
      'fsd/insignificant-slice': 'off',
    },
  },
])
