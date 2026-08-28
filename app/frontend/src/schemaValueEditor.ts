import type { E2CategorySchemaProperty } from './types'

export type SchemaChoiceOption = {
  value: string
  label: string
}

/**
 * Convert the different value shapes returned by DXM's read-only endpoints
 * into the stable option ids used by the editor schema.  The same helper is
 * used when a template is applied and when a saved plan is hydrated; this is
 * important because DXM sometimes returns an option id, sometimes an option
 * object, and sometimes the Chinese display name.
 */
export function normalizeSchemaValueForDefinition(
  definition: E2CategorySchemaProperty,
  value: unknown,
): unknown {
  if (value === undefined || value === null) return value
  const options = resolveSchemaChoiceOptions(definition)
  if (options?.length) {
    if (definition.type === 'array') {
      const rawItems = Array.isArray(value) ? value : [value]
      return rawItems
        .map((item) => normalizeChoiceValue(item, options))
        .filter((item): item is string => item !== undefined)
    }
    return normalizeChoiceValue(value, options) ?? value
  }
  if (definition.type === 'boolean' && typeof value === 'string') {
    if (value.trim().toLowerCase() === 'true') return true
    if (value.trim().toLowerCase() === 'false') return false
  }
  if (definition.type === 'integer' && typeof value === 'string' && /^-?\d+$/.test(value.trim())) {
    return Number.parseInt(value, 10)
  }
  if (definition.type === 'number' && typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) {
    return Number(value)
  }
  return value
}

function normalizeChoiceValue(
  value: unknown,
  options: SchemaChoiceOption[],
): string | undefined {
  if (value === undefined || value === null) return undefined
  if (typeof value === 'object' && !Array.isArray(value)) {
    const record = value as Record<string, unknown>
    const id = record.id ?? record.valueId ?? record.value_id ?? record.idStr ?? record.code ?? record.value
    if (id !== undefined && id !== null) return normalizeChoiceValue(id, options)
    const label = record.nameZh ?? record.label ?? record.text ?? record.name
    if (label !== undefined && label !== null) return normalizeChoiceValue(label, options)
    return undefined
  }
  const raw = String(value).trim()
  if (!raw) return undefined
  const exactId = options.find((option) => option.value === raw)
  if (exactId) return exactId.value
  const exactLabel = options.find((option) => option.label === raw)
  if (exactLabel) return exactLabel.value
  // Labels are rendered as "中文名称 · real-id".  Accept a value copied from
  // that presentation without ever persisting the presentation string.
  const withoutId = raw.split(' · ')[0]
  const byDisplay = options.find((option) => option.label.split(' · ')[0] === withoutId)
  return byDisplay?.value ?? raw
}

export function resolveSchemaChoiceOptions(
  definition: E2CategorySchemaProperty,
): SchemaChoiceOption[] | null {
  const rawValues = Array.isArray(definition.values) && definition.values.length > 0
    ? definition.values
    : definition.type === 'array' && definition.items && Array.isArray(definition.items.values)
      ? definition.items.values
      : []
  if (rawValues.length > 0) {
    return rawValues.flatMap((item) => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) {
        return item === undefined || item === null ? [] : [{ value: String(item), label: String(item) }]
      }
      const record = item as Record<string, unknown>
      const id = record.id ?? record.valueId ?? record.value_id ?? record.idStr ?? record.code ?? record.value
      if (id === undefined || id === null || String(id).trim() === '') return []
      const names = record.names && typeof record.names === 'object' && !Array.isArray(record.names)
        ? record.names as Record<string, unknown>
        : {}
      const label = names.zh ?? record.nameZh ?? record.label ?? record.text ?? record.name ?? names.en ?? record.nameEn ?? id
      return [{ value: String(id), label: `${String(label)} · ${id}` }]
    })
  }
  if (Array.isArray(definition.enum) && definition.enum.length > 0) {
    return definition.enum.map((item) => ({
      value: String(item),
      label: String(item),
    }))
  }
  return null
}
