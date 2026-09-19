import React, { useState, useRef } from 'react';
import { api } from '@/services/api';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  UploadCloud,
  FileText,
  Image as ImageIcon,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  RotateCcw,
  Loader2,
  FileCheck,
  Layers,
  Sparkles,
  ScanText,
  Tag,
  Brain,
  FileSpreadsheet,
  UserCheck,
  HelpCircle,
} from 'lucide-react';

const MAX_FILE_SIZE_MB = 10;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

const ALLOWED_EXTENSIONS = ['.pdf', '.jpg', '.jpeg', '.png'];
const ALLOWED_MIME_TYPES = ['application/pdf', 'image/jpeg', 'image/png', 'image/jpg'];

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function getFileTypeBadge(filename, mimeType) {
  const lower = (filename || '').toLowerCase();
  if (lower.endsWith('.pdf') || mimeType === 'application/pdf') {
    return { label: 'PDF', color: 'bg-red-500/10 text-red-400 border-red-500/20', isPdf: true };
  }
  if (lower.endsWith('.png') || mimeType === 'image/png') {
    return { label: 'PNG', color: 'bg-blue-500/10 text-blue-400 border-blue-500/20', isPdf: false };
  }
  return { label: 'JPG', color: 'bg-amber-500/10 text-amber-400 border-amber-500/20', isPdf: false };
}

export default function DocumentUpload({ onUploadSuccess }) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [error, setError] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadedDoc, setUploadedDoc] = useState(null);
  const [preprocessing, setPreprocessing] = useState(false);
  const [preprocessResult, setPreprocessResult] = useState(null);
  const [runningOcr, setRunningOcr] = useState(false);
  const [ocrProgressText, setOcrProgressText] = useState('');
  const [ocrResult, setOcrResult] = useState(null);
  const [viewMode, setViewMode] = useState('full');
  const [classifying, setClassifying] = useState(false);
  const [classificationResult, setClassificationResult] = useState(null);
  const inputRef = useRef(null);

  const validateFile = (file) => {
    if (!file) return false;

    // Check size
    if (file.size > MAX_FILE_SIZE_BYTES) {
      setError(`File is too large (${formatBytes(file.size)}). Maximum size is ${MAX_FILE_SIZE_MB} MB.`);
      return false;
    }

    // Check extension & MIME
    const nameLower = file.name.toLowerCase();
    const hasValidExt = ALLOWED_EXTENSIONS.some((ext) => nameLower.endsWith(ext));
    const hasValidMime = ALLOWED_MIME_TYPES.includes(file.type?.toLowerCase());

    if (!hasValidExt && !hasValidMime) {
      setError('File type not supported. Please upload a PDF, JPG, or PNG.');
      return false;
    }

    setError(null);
    return true;
  };

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (validateFile(file)) {
        setSelectedFile(file);
        setUploadedDoc(null);
      }
    }
  };

  const handleChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      if (validateFile(file)) {
        setSelectedFile(file);
        setUploadedDoc(null);
      }
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) return;

    setUploading(true);
    setError(null);

    const result = await api.uploadDocument(selectedFile);

    setUploading(false);

    if (result.ok && result.data) {
      setUploadedDoc(result.data);
      setPreprocessResult(null);
      setSelectedFile(null);
      if (onUploadSuccess) {
        onUploadSuccess(result.data);
      }
    } else {
      setError(result.error || 'Upload failed. Please try again.');
    }
  };

  const handlePreprocess = async () => {
    if (!uploadedDoc?.id) return;

    setPreprocessing(true);
    setError(null);

    const result = await api.preprocessDocument(uploadedDoc.id);

    setPreprocessing(false);

    if (result.ok && result.data) {
      setPreprocessResult(result.data);
      setUploadedDoc((prev) => ({
        ...prev,
        status: 'preprocessed',
      }));
    } else {
      setError(result.error || 'Preprocessing failed. Please try again.');
    }
  };

  const handleRunOcr = async () => {
    if (!uploadedDoc?.id) return;

    setRunningOcr(true);
    setError(null);
    setOcrProgressText('Running OCR...');

    const totalPages = preprocessResult?.page_count || 1;
    let pageTimer = null;
    if (totalPages > 1) {
      let page = 1;
      pageTimer = setInterval(() => {
        if (page <= totalPages) {
          setOcrProgressText(`Processing page ${page} of ${totalPages}...`);
          page += 1;
        }
      }, 750);
    }

    const result = await api.runOcr(uploadedDoc.id);

    if (pageTimer) clearInterval(pageTimer);
    setRunningOcr(false);
    setOcrProgressText('');

    if (result.ok && result.data) {
      setOcrResult(result.data);
      setUploadedDoc((prev) => ({
        ...prev,
        status: 'ocr_completed',
      }));
    } else {
      setError(result.error || 'OCR extraction failed. Please try again.');
    }
  };

  const handleClassify = async () => {
    if (!uploadedDoc?.id) return;

    setClassifying(true);
    setError(null);

    const result = await api.classifyDocument(uploadedDoc.id);

    setClassifying(false);

    if (result.ok && result.data) {
      setClassificationResult(result.data);
      setUploadedDoc((prev) => ({
        ...prev,
        status: 'classified',
        document_type: result.data.document_type,
      }));
    } else {
      setError(result.error || 'Classification failed. Please check Gemini API configuration.');
    }
  };

  const handleReset = () => {
    setSelectedFile(null);
    setUploadedDoc(null);
    setPreprocessResult(null);
    setOcrResult(null);
    setClassificationResult(null);
    setRunningOcr(false);
    setClassifying(false);
    setOcrProgressText('');
    setError(null);
    if (inputRef.current) {
      inputRef.current.value = '';
    }
  };

  return (
    <Card className="w-full max-w-xl mx-auto border-border/60 bg-card/60 backdrop-blur-xl shadow-2xl text-left">
      <CardHeader className="pb-3 border-b border-border/40">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <UploadCloud className="h-5 w-5 text-primary" />
            <CardTitle className="text-base text-white">Document Ingestion</CardTitle>
          </div>
          <Badge variant="outline" className="text-[11px] font-mono border-border/50 text-muted-foreground">
            Phase 3 Pipeline
          </Badge>
        </div>
        <CardDescription className="text-xs text-muted-foreground">
          Upload PDF, JPG, or PNG files up to 10 MB for safe pipeline storage
        </CardDescription>
      </CardHeader>

      <CardContent className="pt-5 space-y-4">
        {/* Error Alert */}
        {error && (
          <div className="flex items-start gap-2.5 rounded-lg border border-rose-500/30 bg-rose-950/20 p-3 text-xs text-rose-300">
            <AlertCircle className="h-4 w-4 text-rose-400 shrink-0 mt-0.5" />
            <div className="flex-1">{error}</div>
          </div>
        )}

        {/* Pipeline Step Progress Indicator */}
        {uploadedDoc && (
          <div className="flex items-center justify-between rounded-lg border border-border/50 bg-background/50 px-3.5 py-2 text-[11px] font-mono">
            <div className="flex items-center gap-1.5 text-emerald-400 font-semibold">
              <CheckCircle2 className="h-3.5 w-3.5" /> Upload
            </div>
            <span className="text-muted-foreground/60">→</span>
            <div className={`flex items-center gap-1.5 ${preprocessResult ? 'text-emerald-400 font-semibold' : 'text-muted-foreground'}`}>
              {preprocessResult ? <CheckCircle2 className="h-3.5 w-3.5" /> : <span className="h-1.5 w-1.5 rounded-full bg-slate-600" />} Preprocess
            </div>
            <span className="text-muted-foreground/60">→</span>
            <div className={`flex items-center gap-1.5 ${ocrResult ? 'text-emerald-400 font-semibold' : (preprocessResult ? 'text-blue-400 font-semibold' : 'text-muted-foreground')}`}>
              {ocrResult ? <CheckCircle2 className="h-3.5 w-3.5" /> : <span className={`h-1.5 w-1.5 rounded-full ${preprocessResult ? 'bg-blue-400' : 'bg-slate-600'}`} />} OCR
            </div>
            <span className="text-muted-foreground/60">→</span>
            <div className={`flex items-center gap-1.5 ${classificationResult ? 'text-emerald-400 font-semibold' : (ocrResult ? 'text-purple-400 font-semibold animate-pulse' : 'text-muted-foreground')}`}>
              {classificationResult ? <CheckCircle2 className="h-3.5 w-3.5" /> : <span className={`h-1.5 w-1.5 rounded-full ${ocrResult ? 'bg-purple-400' : 'bg-slate-600'}`} />} Classify
            </div>
          </div>
        )}

        {/* State 1: Upload Success Result Card */}
        {uploadedDoc ? (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-emerald-400 text-xs font-semibold">
                <CheckCircle2 className="h-4 w-4" />
                <span>
                  {preprocessResult
                    ? "Document prepared for OCR"
                    : "Document uploaded successfully"}
                </span>
              </div>
              <Badge
                variant={
                  uploadedDoc.status === "classified"
                    ? "default"
                    : uploadedDoc.status === "ocr_completed"
                      ? "success"
                      : uploadedDoc.status === "preprocessed"
                        ? "secondary"
                        : "outline"
                }
                className="capitalize text-xs font-mono"
              >
                Status: {uploadedDoc.status || "uploaded"}
              </Badge>
            </div>

            <div className="rounded-xl border border-border/60 bg-background/50 p-4 space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 border border-primary/20 text-primary">
                    {uploadedDoc.mime_type === "application/pdf" ? (
                      <FileText className="h-5 w-5 text-red-400" />
                    ) : (
                      <ImageIcon className="h-5 w-5 text-blue-400" />
                    )}
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold text-white truncate max-w-[260px] sm:max-w-[320px]">
                      {uploadedDoc.filename}
                    </h4>
                    <div className="flex items-center gap-2 mt-0.5 text-xs text-muted-foreground">
                      <span>{formatBytes(uploadedDoc.file_size)}</span>
                      <span>•</span>
                      <span className="capitalize">{uploadedDoc.document_type || "Unknown Type"}</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Preprocessed Details Badge / Banner */}
              {preprocessResult && !ocrResult && (
                <div className="rounded-lg border border-indigo-500/20 bg-indigo-950/20 p-2.5 text-[11px] font-mono text-muted-foreground space-y-1.5">
                  <div className="flex items-center justify-between text-indigo-300 font-semibold">
                    <span className="flex items-center gap-1.5">
                      <Layers className="h-3.5 w-3.5" /> Pages Generated:
                    </span>
                    <span>{preprocessResult.page_count} Pages</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Format:</span>
                    <span className="text-slate-200">
                      {preprocessResult.mime_type?.includes("pdf") ? "PDF (200 DPI PNGs)" : "Normalized PNG"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Processing Duration:</span>
                    <span className="text-slate-200">{preprocessResult.metadata?.processing_duration_ms} ms</span>
                  </div>
                </div>
              )}

              {/* OCR Results Panel */}
              {ocrResult && (
                <div className="rounded-lg border border-blue-500/30 bg-blue-950/20 p-3 text-xs font-mono space-y-2.5">
                  <div className="flex items-center justify-between text-blue-300 font-semibold border-b border-blue-500/20 pb-2">
                    <span className="flex items-center gap-1.5 text-emerald-400">
                      <CheckCircle2 className="h-4 w-4" /> OCR Completed
                    </span>
                    <span className="text-[11px] text-blue-300 font-mono">
                      Engine: {ocrResult.metadata?.ocr_engine || 'Tesseract'}
                    </span>
                  </div>

                  <div className="grid grid-cols-3 gap-2 py-0.5 text-center">
                    <div className="rounded bg-background/60 p-2 border border-border/40">
                      <div className="text-[10px] text-muted-foreground uppercase">Pages</div>
                      <div className="text-sm font-bold text-white">{ocrResult.page_count}</div>
                    </div>
                    <div className="rounded bg-background/60 p-2 border border-border/40">
                      <div className="text-[10px] text-muted-foreground uppercase">Text Blocks</div>
                      <div className="text-sm font-bold text-white">{ocrResult.metadata?.block_count ?? 0}</div>
                    </div>
                    <div className="rounded bg-background/60 p-2 border border-border/40">
                      <div className="text-[10px] text-muted-foreground uppercase">Avg Confidence</div>
                      <div className="text-sm font-bold text-emerald-400">
                        {ocrResult.metadata?.average_confidence != null
                          ? `${ocrResult.metadata.average_confidence}%`
                          : 'N/A'}
                      </div>
                    </div>
                  </div>

                  {/* Extracted Text Preview */}
                  <div className="pt-2 border-t border-border/40 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-slate-200">Extracted Text</span>
                      <div className="flex items-center gap-1 bg-background/80 p-0.5 rounded border border-border/40 text-[10px]">
                        <button
                          type="button"
                          onClick={() => setViewMode('full')}
                          className={`px-2 py-0.5 rounded ${viewMode === 'full' ? 'bg-primary text-white font-medium' : 'text-muted-foreground hover:text-white'}`}
                        >
                          Full Text
                        </button>
                        <button
                          type="button"
                          onClick={() => setViewMode('blocks')}
                          className={`px-2 py-0.5 rounded ${viewMode === 'blocks' ? 'bg-primary text-white font-medium' : 'text-muted-foreground hover:text-white'}`}
                        >
                          Blocks ({ocrResult.metadata?.block_count ?? 0})
                        </button>
                      </div>
                    </div>

                    {viewMode === 'full' ? (
                      <div className="max-h-48 overflow-y-auto rounded-md bg-background/80 p-2.5 text-[11px] font-mono text-slate-300 whitespace-pre-wrap leading-relaxed border border-border/40 select-text">
                        {ocrResult.full_text || 'No readable text detected.'}
                      </div>
                    ) : (
                      <div className="max-h-48 overflow-y-auto space-y-1.5 pr-1">
                        {ocrResult.pages?.flatMap((p) => p.blocks || []).slice(0, 50).map((b, idx) => (
                          <div key={idx} className="rounded bg-background/70 p-2 border border-border/40 flex items-start justify-between gap-2 text-[11px]">
                            <div className="truncate text-slate-200 font-mono flex-1">
                              <span className="text-muted-foreground mr-1.5">#{b.block_index}</span>
                              {b.text}
                            </div>
                            <div className="shrink-0 flex items-center gap-1.5 text-[10px] font-mono">
                              <span className="text-muted-foreground">P{b.page_number}</span>
                              <span className="text-muted-foreground">[{b.bbox.x},{b.bbox.y}]</span>
                              <span className={b.confidence != null && b.confidence >= 80 ? 'text-emerald-400' : 'text-amber-400'}>
                                {b.confidence != null ? `${b.confidence}%` : 'N/A'}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Classification Results Panel */}
              {classificationResult && (
                <div className="rounded-lg border border-purple-500/30 bg-purple-950/20 p-3.5 text-xs font-mono space-y-2.5">
                  <div className="flex items-center justify-between border-b border-purple-500/20 pb-2">
                    <div className="flex items-center gap-2 text-purple-300 font-semibold">
                      <Brain className="h-4 w-4 text-purple-400" />
                      <span>Document Classification</span>
                    </div>
                    <Badge
                      variant={
                        classificationResult.document_type === "invoice"
                          ? "default"
                          : classificationResult.document_type === "onboarding_form"
                            ? "success"
                            : "warning"
                      }
                      className="capitalize text-xs font-mono px-2 py-0.5"
                    >
                      {classificationResult.document_type === "invoice" && "Invoice"}
                      {classificationResult.document_type === "onboarding_form" && "Onboarding Form"}
                      {classificationResult.document_type === "unknown" && "Unknown"}
                    </Badge>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-center">
                    <div className="rounded bg-background/60 p-2 border border-border/40">
                      <div className="text-[10px] text-muted-foreground uppercase">Document Archetype</div>
                      <div className="text-sm font-bold capitalize text-white">
                        {classificationResult.document_type.replace("_", " ")}
                      </div>
                    </div>
                    <div className="rounded bg-background/60 p-2 border border-border/40">
                      <div className="text-[10px] text-muted-foreground uppercase">AI Confidence</div>
                      <div className="text-sm font-bold text-purple-300">
                        {Math.round(classificationResult.confidence * 100)}%
                      </div>
                    </div>
                  </div>

                  {classificationResult.evidence?.length > 0 && (
                    <div className="pt-2 border-t border-border/40 space-y-1">
                      <div className="text-[11px] font-semibold text-slate-200">Classification Evidence:</div>
                      <ul className="space-y-1">
                        {classificationResult.evidence.map((ev, i) => (
                          <li key={i} className="flex items-start gap-1.5 text-slate-300 text-[11px]">
                            <span className="text-purple-400 font-bold">•</span>
                            <span>{ev}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {classificationResult.document_type === "unknown" && (
                    <div className="rounded bg-amber-500/10 border border-amber-500/20 p-2 text-[10px] text-amber-300 leading-relaxed">
                      Document does not match supported archetypes (Invoice or Onboarding Form). It will be flagged for manual review or secondary routing.
                    </div>
                  )}
                </div>
              )}

              <div className="pt-2 border-t border-border/40 text-[11px] font-mono text-muted-foreground space-y-1">
                <div className="flex items-center justify-between">
                  <span>Document ID:</span>
                  <span className="text-slate-300 truncate max-w-[220px]">{uploadedDoc.id}</span>
                </div>
                {uploadedDoc.storage_path && (
                  <div className="flex items-center justify-between">
                    <span>Storage Path:</span>
                    <span className="text-slate-300 truncate max-w-[220px]">{uploadedDoc.storage_path}</span>
                  </div>
                )}
              </div>
            </div>

            {/* Actions for uploaded document */}
            <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
              <Button
                variant="outline"
                size="sm"
                onClick={handleReset}
                className="text-xs gap-1.5"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Upload Another
              </Button>

              <div className="flex items-center gap-2">
                {uploadedDoc.preview_url && (
                  <Button
                    size="sm"
                    variant="outline"
                    asChild
                    className="text-xs gap-1.5"
                  >
                    <a
                      href={uploadedDoc.preview_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                      View Document
                    </a>
                  </Button>
                )}

                {uploadedDoc.status !== "preprocessed" && uploadedDoc.status !== "ocr_completed" && uploadedDoc.status !== "classified" && !preprocessResult ? (
                  <Button
                    size="sm"
                    onClick={handlePreprocess}
                    disabled={preprocessing}
                    className="text-xs gap-1.5 bg-indigo-600 hover:bg-indigo-500 text-white shadow-md shadow-indigo-500/20"
                  >
                    {preprocessing ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Preparing document...
                      </>
                    ) : (
                      <>
                        <Layers className="h-3.5 w-3.5" />
                        Prepare for OCR
                      </>
                    )}
                  </Button>
                ) : !ocrResult ? (
                  <Button
                    size="sm"
                    onClick={handleRunOcr}
                    disabled={runningOcr}
                    className="text-xs gap-1.5 bg-blue-600 hover:bg-blue-500 text-white shadow-md shadow-blue-500/20"
                  >
                    {runningOcr ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        {ocrProgressText || "Running OCR..."}
                      </>
                    ) : (
                      <>
                        <ScanText className="h-3.5 w-3.5" />
                        Run OCR
                      </>
                    )}
                  </Button>
                ) : !classificationResult ? (
                  <Button
                    size="sm"
                    onClick={handleClassify}
                    disabled={classifying}
                    className="text-xs gap-1.5 bg-purple-600 hover:bg-purple-500 text-white shadow-md shadow-purple-500/20"
                  >
                    {classifying ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Classifying document...
                      </>
                    ) : (
                      <>
                        <Tag className="h-3.5 w-3.5" />
                        Classify Document
                      </>
                    )}
                  </Button>
                ) : (
                  <Badge variant="default" className="text-xs gap-1 py-1 px-2.5 bg-purple-600/20 border-purple-500/40 text-purple-300">
                    <CheckCircle2 className="h-3.5 w-3.5 text-purple-400" />
                    Classified
                  </Badge>
                )}
              </div>
            </div>
          </div>
        ) : (
          /* State 2: Dropzone & File Selection */
          <div className="space-y-4">
            <div
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={() => inputRef.current?.click()}
              className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center cursor-pointer transition-all duration-200 ${dragActive
                ? 'border-primary bg-primary/10 scale-[1.01]'
                : 'border-border/60 hover:border-primary/50 hover:bg-card/50'
                }`}
            >
              <input
                ref={inputRef}
                type="file"
                className="hidden"
                accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
                onChange={handleChange}
              />

              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 border border-primary/20 text-primary mb-3 shadow-[0_0_15px_rgba(59,130,246,0.2)]">
                <UploadCloud className="h-6 w-6" />
              </div>

              <div className="space-y-1 mb-3">
                <p className="text-sm font-medium text-white">
                  Drag & drop your document here
                </p>
                <p className="text-xs text-muted-foreground">
                  or <span className="text-primary font-semibold underline underline-offset-2">browse file</span> from your computer
                </p>
              </div>

              <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                <span className="px-2 py-0.5 rounded bg-muted/50 border border-border/40 font-mono">PDF</span>
                <span className="px-2 py-0.5 rounded bg-muted/50 border border-border/40 font-mono">JPG</span>
                <span className="px-2 py-0.5 rounded bg-muted/50 border border-border/40 font-mono">PNG</span>
                <span>• Max 10 MB</span>
              </div>
            </div>

            {/* Selected File Inspection & Action */}
            {selectedFile && (
              <div className="rounded-lg border border-primary/30 bg-primary/5 p-3.5 flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 overflow-hidden">
                  <FileCheck className="h-5 w-5 text-primary shrink-0" />
                  <div className="overflow-hidden">
                    <p className="text-xs font-semibold text-white truncate max-w-[240px] sm:max-w-[280px]">
                      {selectedFile.name}
                    </p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[11px] text-muted-foreground font-mono">
                        {formatBytes(selectedFile.size)}
                      </span>
                      <span className={`text-[10px] px-1.5 py-0.2 rounded border font-semibold ${getFileTypeBadge(selectedFile.name, selectedFile.type).color}`}>
                        {getFileTypeBadge(selectedFile.name, selectedFile.type).label}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleReset}
                    disabled={uploading}
                    className="text-xs text-muted-foreground hover:text-white"
                  >
                    Clear
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleUpload}
                    disabled={uploading}
                    className="text-xs gap-1.5 shadow-md shadow-primary/20"
                  >
                    {uploading ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Uploading...
                      </>
                    ) : (
                      <>
                        <UploadCloud className="h-3.5 w-3.5" />
                        Upload Document
                      </>
                    )}
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
