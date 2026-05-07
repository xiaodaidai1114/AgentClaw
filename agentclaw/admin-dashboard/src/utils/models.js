export function getModelType(model) {
  return String(model?.model_type || model?.type || '').trim().toLowerCase()
}

export function isConversationModel(model) {
  const modelType = getModelType(model)
  const modelId = String(model?.id || '').trim().toLowerCase()
  if (['embedding', 'rerank'].includes(modelType)) return false
  if (!modelType && /(embedding|rerank|reranker|重排|嵌入)/.test(modelId)) return false
  return true
}

export function toConversationModelOptions(models = []) {
  return models
    .filter(isConversationModel)
    .map((item) => ({ label: item.id, value: item.id }))
}
