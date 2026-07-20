import type { InputRef } from 'antd'

declare global {
  interface HTMLInputElement extends Pick<InputRef, 'input' | 'nativeElement'> {}
}

export {}
