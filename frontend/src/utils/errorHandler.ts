/**
 * API 错误处理模块
 *
 * 统一处理 API 请求错误，提供友好的错误提示。
 */

/**
 * 错误类型
 */
export enum ErrorType {
  NETWORK_ERROR = 'NETWORK_ERROR',
  API_ERROR = 'API_ERROR',
  TIMEOUT_ERROR = 'TIMEOUT_ERROR',
  UNAUTHORIZED = 'UNAUTHORIZED',
  UNKNOWN_ERROR = 'UNKNOWN_ERROR',
}

/**
 * 错误信息映射
 */
const errorMessages: Record<ErrorType, string> = {
  [ErrorType.NETWORK_ERROR]: '网络连接失败，请检查网络或后端服务是否正常',
  [ErrorType.API_ERROR]: '请求失败，请稍后重试',
  [ErrorType.TIMEOUT_ERROR]: '请求超时，请稍后重试',
  [ErrorType.UNAUTHORIZED]: '未授权，请登录后重试',
  [ErrorType.UNKNOWN_ERROR]: '发生未知错误，请联系管理员',
}

/**
 * 获取错误消息
 */
export const getErrorMessage = (error: unknown, type?: ErrorType): string => {
  if (type) {
    return errorMessages[type]
  }

  if (error instanceof Error) {
    return error.message
  }

  return errorMessages[ErrorType.UNKNOWN_ERROR]
}

/**
 * 判断错误类型
 */
export const getErrorType = (error: unknown): ErrorType => {
  if (error instanceof TypeError) {
    if (error.message.includes('timeout')) {
      return ErrorType.TIMEOUT_ERROR
    }
    if (error.message.includes('NetworkError') || error.message.includes('fetch')) {
      return ErrorType.NETWORK_ERROR
    }
    return ErrorType.NETWORK_ERROR
  }

  if (error instanceof Error) {
    const message = error.message.toLowerCase()
    if (message.includes('401') || message.includes('unauthorized')) {
      return ErrorType.UNAUTHORIZED
    }
    if (message.includes('timeout')) {
      return ErrorType.TIMEOUT_ERROR
    }
    if (message.includes('network') || message.includes('fetch')) {
      return ErrorType.NETWORK_ERROR
    }
    return ErrorType.API_ERROR
  }

  return ErrorType.UNKNOWN_ERROR
}

/**
 * 处理 API 响应错误
 */
export const handleApiError = (response: Response): Promise<never> => {
  const status = response.status

  switch (status) {
    case 401:
      throw new Error('未授权访问')
    case 403:
      throw new Error('无权访问')
    case 404:
      throw new Error('请求的资源不存在')
    case 500:
      throw new Error('服务器内部错误')
    case 502:
      throw new Error('网关错误')
    case 503:
      throw new Error('服务暂时不可用')
    default:
      throw new Error(`请求失败 (${status})`)
  }
}

/**
 * 获取错误类型中文消息
 */
export const getErrorTypeMessage = (type: ErrorType): string => {
  const messages: Record<ErrorType, string> = {
    [ErrorType.NETWORK_ERROR]: '网络连接失败，请检查网络或后端服务是否正常',
    [ErrorType.API_ERROR]: '请求失败，请稍后重试',
    [ErrorType.TIMEOUT_ERROR]: '请求超时，请稍后重试',
    [ErrorType.UNAUTHORIZED]: '未授权，请登录后重试',
    [ErrorType.UNKNOWN_ERROR]: '发生未知错误，请联系管理员',
  }
  return messages[type]
}
