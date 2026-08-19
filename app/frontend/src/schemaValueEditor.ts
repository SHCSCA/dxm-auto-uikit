import type { E2CategorySchemaProperty } from './types'

export type SchemaChoiceOption = {
  value: string
  label: string
}

export function resolveSchemaChoiceOptions(
  definition: E2CategorySchemaProperty,
): SchemaChoiceOption[] | null {
  if (Array.isArray(definition.values) && definition.values.length > 0) {
    return definition.values.map((item) => ({
      value: String(item.id),
      label: item.names?.zh
        ? `${item.names.zh} · ${item.id}`
        : item.name
          ? `${item.name} · ${item.id}`
          : String(item.id),
    }))
  }
  if (Array.isArray(definition.enum) && definition.enum.length > 0) {
    return definition.enum.map((item) => ({
      value: String(item),
      label: String(item),
    }))
  }
  return null
}
