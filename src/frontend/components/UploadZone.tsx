import { useRef, useState, type DragEvent, type ChangeEvent } from 'react'
import { Icon } from './Icon'

interface Props {
  onUpload: (file: File) => Promise<unknown>
  uploading: boolean
  compact?: boolean
}

const ACCEPTED = ['.pdf', '.docx', '.xlsx']

export function UploadZone({ onUpload, uploading, compact = false }: Props) {
  const [dragActive, setDragActive] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    const file = files[0]
    const ok = ACCEPTED.some((ext) => file.name.toLowerCase().endsWith(ext))
    if (!ok) {
      alert(`只支持 ${ACCEPTED.join(' / ')} 文件`)
      return
    }
    await onUpload(file)
  }

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragActive(false)
    handleFiles(e.dataTransfer.files)
  }

  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragActive(true)
  }

  const onDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragActive(false)
  }

  const onChange = (e: ChangeEvent<HTMLInputElement>) => {
    handleFiles(e.target.files)
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <div
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onClick={() => inputRef.current?.click()}
      className={`dm-upload-zone ${compact ? 'is-compact' : ''} ${dragActive ? 'is-dragging' : ''} ${uploading ? 'pointer-events-none opacity-60' : ''}`}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED.join(',')}
        onChange={onChange}
        className="hidden"
      />
      <div className="dm-upload-content">
        <Icon name="upload" size={compact ? 16 : 27} />
        <div className="dm-upload-title">{uploading ? '正在解析资料…' : compact ? '导入文件' : '拖拽文件到这里，或点击选择'}</div>
        <div className="dm-upload-hint">支持 PDF / DOCX，导入后自动建立索引</div>
      </div>
    </div>
  )
}
