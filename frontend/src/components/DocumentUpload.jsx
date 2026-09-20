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
  FolderTree,
  ChevronDown,
  ChevronRight,
  Boxes,
  ShieldCheck,
  CheckSquare,
  Eye,
  AlertTriangle,
} from 'lucide-react';

function formatSectionTitle(sectionName) {
  if (!sectionName) return 'Unknown Section';
  return sectionName
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function formatFieldName(fieldName) {
  if (!fieldName) return '';
  return fieldName
    .replace(/^line_item_\d+_/, '')
    .replace(/^id_doc_\d+_/, '')
    .replace(/^agreement_\d+_/, '')
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

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
  const [detectingSections, setDetectingSections] = useState(false);
  const [sectionsResult, setSectionsResult] = useState(null);
  const [sectionsError, setSectionsError] = useState(null);
  const [expandedSections, setExpandedSections] = useState({});
  const [extracting, setExtracting] = useState(false);
  const [extractionResult, setExtractionResult] = useState(null);
  const [extractionError, setExtractionError] = useState(null);
  const [expandedFields, setExpandedFields] = useState({});
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState(null);
  const [validationError, setValidationError] = useState(null);
  const [recoveringVision, setRecoveringVision] = useState(false);
  const [visionResult, setVisionResult] = useState(null);
  const [visionError, setVisionError] = useState(null);
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

  const handleDetectSections = async () => {
    if (!uploadedDoc?.id) return;
    setDetectingSections(true);
    setSectionsError(null);

    const result = await api.detectSections(uploadedDoc.id);
    setDetectingSections(false);

    if (result.ok && result.data) {
      setSectionsResult(result.data);
      setUploadedDoc((prev) => ({
        ...prev,
        status: 'sectioned',
      }));
    } else {
      setSectionsError(result.error || 'Section detection failed.');
    }
  };

  const handleExtractFields = async () => {
    if (!uploadedDoc?.id) return;
    setExtracting(true);
    setExtractionError(null);

    const result = await api.extractFields(uploadedDoc.id);
    setExtracting(false);

    if (result.ok && result.data) {
      setExtractionResult(result.data);
      if (result.data.status !== 'skipped') {
        setUploadedDoc((prev) => ({
          ...prev,
          status: 'extracted',
        }));
      }
    } else {
      setExtractionError(result.error || 'Structured field extraction failed.');
    }
  };

  const handleValidate = async () => {
    if (!uploadedDoc?.id) return;
    setValidating(true);
    setValidationError(null);

    const result = await api.validateDocument(uploadedDoc.id);
    setValidating(false);

    if (result.ok && result.data) {
      setValidationResult(result.data);
      setUploadedDoc((prev) => ({
        ...prev,
        status: result.data.document_status,
      }));
    } else {
      setValidationError(result.error || 'Validation failed.');
    }
  };

  const handleVisionFallback = async () => {
    if (!uploadedDoc?.id) return;
    setRecoveringVision(true);
    setVisionError(null);

    const result = await api.runVisionFallback(uploadedDoc.id);
    setRecoveringVision(false);

    if (result.ok && result.data) {
      setVisionResult(result.data);
      if (result.data.updated_validation) {
        setValidationResult(result.data.updated_validation);
        setUploadedDoc((prev) => ({
          ...prev,
          status: result.data.updated_validation.document_status,
        }));
      }
    } else {
      setVisionError(result.error || 'Vision fallback recovery failed.');
    }
  };

  const toggleSection = (idx) => {
    setExpandedSections((prev) => ({
      ...prev,
      [idx]: !prev[idx],
    }));
  };

  const toggleField = (key) => {
    setExpandedFields((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const handleReset = () => {
    setSelectedFile(null);
    setUploadedDoc(null);
    setPreprocessResult(null);
    setOcrResult(null);
    setClassificationResult(null);
    setSectionsResult(null);
    setExtractionResult(null);
    setValidationResult(null);
    setVisionResult(null);
    setRunningOcr(false);
    setClassifying(false);
    setDetectingSections(false);
    setExtracting(false);
    setValidating(false);
    setRecoveringVision(false);
    setSectionsError(null);
    setExtractionError(null);
    setValidationError(null);
    setVisionError(null);
    setExpandedSections({});
    setExpandedFields({});
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
            Phase 10 Pipeline
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

        {validationError && (
          <div className="flex items-start gap-2.5 rounded-lg border border-rose-500/30 bg-rose-950/20 p-3 text-xs text-rose-300">
            <AlertCircle className="h-4 w-4 text-rose-400 shrink-0 mt-0.5" />
            <div className="flex-1">{validationError}</div>
          </div>
        )}

        {/* Pipeline Step Progress Indicator */}
        {uploadedDoc && (
          <div className="flex items-center justify-between rounded-lg border border-border/50 bg-background/50 px-3 py-2 text-[11px] font-mono overflow-x-auto gap-1">
            <div className="flex items-center gap-1 text-emerald-400 font-semibold shrink-0">
              <CheckCircle2 className="h-3.5 w-3.5" /> Upload
            </div>
            <span className="text-muted-foreground/60 shrink-0">→</span>
            <div className={`flex items-center gap-1 shrink-0 ${preprocessResult ? 'text-emerald-400 font-semibold' : 'text-muted-foreground'}`}>
              {preprocessResult ? <CheckCircle2 className="h-3.5 w-3.5" /> : <span className="h-1.5 w-1.5 rounded-full bg-slate-600" />} Preprocess
            </div>
            <span className="text-muted-foreground/60 shrink-0">→</span>
            <div className={`flex items-center gap-1 shrink-0 ${ocrResult ? 'text-emerald-400 font-semibold' : (preprocessResult ? 'text-blue-400 font-semibold' : 'text-muted-foreground')}`}>
              {ocrResult ? <CheckCircle2 className="h-3.5 w-3.5" /> : <span className={`h-1.5 w-1.5 rounded-full ${preprocessResult ? 'bg-blue-400' : 'bg-slate-600'}`} />} OCR
            </div>
            <span className="text-muted-foreground/60 shrink-0">→</span>
            <div className={`flex items-center gap-1 shrink-0 ${classificationResult ? 'text-emerald-400 font-semibold' : (ocrResult ? 'text-purple-400 font-semibold animate-pulse' : 'text-muted-foreground')}`}>
              {classificationResult ? <CheckCircle2 className="h-3.5 w-3.5" /> : <span className={`h-1.5 w-1.5 rounded-full ${ocrResult ? 'bg-purple-400' : 'bg-slate-600'}`} />} Classify
            </div>
            <span className="text-muted-foreground/60 shrink-0">→</span>
            <div className={`flex items-center gap-1 shrink-0 ${sectionsResult ? 'text-emerald-400 font-semibold' : (classificationResult ? (classificationResult.document_type === 'unknown' ? 'text-muted-foreground' : 'text-amber-400 font-semibold animate-pulse') : 'text-muted-foreground')}`}>
              {sectionsResult ? <CheckCircle2 className="h-3.5 w-3.5" /> : <span className={`h-1.5 w-1.5 rounded-full ${classificationResult && classificationResult.document_type !== 'unknown' ? 'bg-amber-400' : 'bg-slate-600'}`} />} Sections
            </div>
            <span className="text-muted-foreground/60 shrink-0">→</span>
            <div className={`flex items-center gap-1 shrink-0 ${extractionResult ? (extractionResult.status === 'skipped' ? 'text-amber-400 font-semibold' : 'text-emerald-400 font-semibold') : (sectionsResult ? 'text-cyan-400 font-semibold animate-pulse' : 'text-muted-foreground')}`}>
              {extractionResult ? (extractionResult.status === 'skipped' ? <AlertCircle className="h-3.5 w-3.5 text-amber-400" /> : <CheckCircle2 className="h-3.5 w-3.5" />) : <span className={`h-1.5 w-1.5 rounded-full ${sectionsResult ? 'bg-cyan-400' : 'bg-slate-600'}`} />} Extract
            </div>
            <span className="text-muted-foreground/60 shrink-0">→</span>
            <div className={`flex items-center gap-1 shrink-0 ${validationResult ? (validationResult.document_status === 'completed' ? 'text-emerald-400 font-semibold' : 'text-amber-400 font-semibold') : (extractionResult && extractionResult.status !== 'skipped' ? 'text-emerald-400 font-semibold animate-pulse' : 'text-muted-foreground')}`}>
              {validationResult ? (validationResult.document_status === 'completed' ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" /> : <AlertCircle className="h-3.5 w-3.5 text-amber-400" />) : <span className={`h-1.5 w-1.5 rounded-full ${extractionResult && extractionResult.status !== 'skipped' ? 'bg-emerald-400' : 'bg-slate-600'}`} />} Validate
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
                  {validationResult
                    ? (validationResult.document_status === 'completed' ? "Deterministic validation passed" : "Validation requires review")
                    : extractionResult
                      ? (extractionResult.status === 'skipped' ? "Extraction skipped (Unknown archetype)" : "Fields extracted successfully")
                      : sectionsResult
                        ? "Sections detected"
                        : classificationResult
                          ? "Document classified"
                          : preprocessResult
                            ? "Document prepared for OCR"
                            : "Document uploaded successfully"}
                </span>
              </div>
              <Badge
                variant={
                  uploadedDoc.status === "completed"
                    ? "success"
                    : uploadedDoc.status === "needs_review"
                      ? "warning"
                      : uploadedDoc.status === "extracted"
                        ? "success"
                        : uploadedDoc.status === "sectioned"
                          ? "warning"
                          : uploadedDoc.status === "classified"
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

              {/* Sections Detection Error */}
              {sectionsError && (
                <div className="flex items-start gap-2.5 rounded-lg border border-rose-500/30 bg-rose-950/20 p-3 text-xs text-rose-300">
                  <AlertCircle className="h-4 w-4 text-rose-400 shrink-0 mt-0.5" />
                  <div className="flex-1">{sectionsError}</div>
                </div>
              )}

              {/* Section Detection Results Card */}
              {sectionsResult && (
                <div className="rounded-xl border border-amber-500/30 bg-amber-950/10 p-3.5 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <FolderTree className="h-4 w-4 text-amber-400" />
                      <span className="text-xs font-semibold text-white">Document Sections</span>
                    </div>
                    <Badge
                      variant="warning"
                      className="text-[11px] font-mono px-2 py-0.5"
                    >
                      {sectionsResult.sections?.length || 0} Sections Found
                    </Badge>
                  </div>

                  {sectionsResult.sections?.length === 0 ? (
                    <div className="rounded-lg bg-background/50 border border-border/40 p-3 text-center text-xs text-muted-foreground">
                      No logical sections extracted for this document archetype ({sectionsResult.document_type || "unknown"}).
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {sectionsResult.sections.map((section, idx) => {
                        const isExpanded = !!expandedSections[idx];
                        return (
                          <div
                            key={section.section_id || idx}
                            className="rounded-lg border border-border/50 bg-background/60 overflow-hidden transition-colors hover:border-amber-500/40"
                          >
                            {/* Accordion Header */}
                            <button
                              type="button"
                              onClick={() => toggleSection(idx)}
                              className="w-full flex items-center justify-between p-2.5 text-left text-xs hover:bg-white/5 transition-colors cursor-pointer"
                            >
                              <div className="flex items-center gap-2 font-medium text-slate-200">
                                {isExpanded ? (
                                  <ChevronDown className="h-3.5 w-3.5 text-amber-400 shrink-0" />
                                ) : (
                                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                                )}
                                <span className="font-semibold text-white">
                                  {formatSectionTitle(section.section_name)}
                                </span>
                                <span className="text-[10px] font-mono text-muted-foreground">
                                  (Page {section.page_number})
                                </span>
                              </div>
                              <div className="flex items-center gap-1.5">
                                {section.block_ids?.length > 0 && (
                                  <span className="text-[10px] font-mono text-muted-foreground px-1.5 py-0.5 rounded bg-muted/40">
                                    {section.block_ids.length} blocks
                                  </span>
                                )}
                                <Badge
                                  variant="outline"
                                  className="text-[10px] font-mono border-amber-500/30 text-amber-300 py-0"
                                >
                                  {Math.round((section.confidence || 0) * 100)}%
                                </Badge>
                              </div>
                            </button>

                            {/* Accordion Body */}
                            {isExpanded && (
                              <div className="p-3 pt-1 border-t border-border/40 bg-background/80 space-y-2">
                                <div className="text-[11px] font-mono text-slate-300 whitespace-pre-wrap rounded bg-muted/30 p-2.5 max-h-48 overflow-y-auto leading-relaxed">
                                  {section.text || "No text in section"}
                                </div>
                                {section.bbox && (
                                  <div className="text-[10px] font-mono text-muted-foreground">
                                    BBox: [x={section.bbox.x}, y={section.bbox.y}, {section.bbox.width}x{section.bbox.height}]
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* Extraction Error */}
              {extractionError && (
                <div className="flex items-start gap-2.5 rounded-lg border border-rose-500/30 bg-rose-950/20 p-3 text-xs text-rose-300">
                  <AlertCircle className="h-4 w-4 text-rose-400 shrink-0 mt-0.5" />
                  <div className="flex-1">{extractionError}</div>
                </div>
              )}

              {/* Extraction Results Card */}
              {extractionResult && (
                <div className="rounded-xl border border-cyan-500/30 bg-cyan-950/15 p-3.5 space-y-3">
                  <div className="flex items-center justify-between border-b border-cyan-500/20 pb-2.5">
                    <div className="flex items-center gap-2">
                      <Sparkles className="h-4 w-4 text-cyan-400" />
                      <span className="text-xs font-semibold text-white">Targeted AI Extraction</span>
                    </div>
                    <Badge
                      variant={extractionResult.status === "skipped" ? "outline" : "success"}
                      className={`text-[11px] font-mono px-2 py-0.5 ${extractionResult.status === "skipped" ? "border-amber-500/40 text-amber-300" : "bg-cyan-500/20 border-cyan-500/40 text-cyan-300"}`}
                    >
                      {extractionResult.status === "skipped"
                        ? "Skipped"
                        : `${extractionResult.field_count || extractionResult.fields?.length || 0} Fields Extracted`}
                    </Badge>
                  </div>

                  {extractionResult.status === "skipped" ? (
                    <div className="rounded-lg bg-amber-500/10 border border-amber-500/20 p-3 text-xs text-amber-300 space-y-1">
                      <div className="font-semibold flex items-center gap-1.5">
                        <AlertCircle className="h-4 w-4" />
                        Structured Extraction Skipped
                      </div>
                      <p className="text-[11px] text-amber-200/80">
                        {extractionResult.reason || "Document archetype is unknown. Extraction requires a recognized document schema (Invoice or Onboarding Form)."}
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {/* Extraction Meta Summary */}
                      <div className="grid grid-cols-3 gap-2 text-center text-xs font-mono">
                        <div className="rounded bg-background/60 p-2 border border-border/40">
                          <div className="text-[10px] text-muted-foreground uppercase">Fields Extracted</div>
                          <div className="text-sm font-bold text-cyan-300">
                            {extractionResult.field_count || extractionResult.fields?.length || 0}
                          </div>
                        </div>
                        <div className="rounded bg-background/60 p-2 border border-border/40">
                          <div className="text-[10px] text-muted-foreground uppercase">Sections Targeted</div>
                          <div className="text-sm font-bold text-white">
                            {Object.keys(extractionResult.section_data || {}).length}
                          </div>
                        </div>
                        <div className="rounded bg-background/60 p-2 border border-border/40">
                          <div className="text-[10px] text-muted-foreground uppercase">Model</div>
                          <div className="text-xs font-bold text-emerald-400 truncate mt-0.5">
                            {extractionResult.metadata?.model || 'Gemini 2.5'}
                          </div>
                        </div>
                      </div>

                      {/* Extracted Fields List with Provenance */}
                      <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                        {(extractionResult.fields || []).map((field, idx) => {
                          const isExpanded = !!expandedFields[idx];
                          const isNull = field.field_value === null || field.field_value === undefined;
                          return (
                            <div
                              key={idx}
                              className="rounded-lg border border-border/50 bg-background/60 p-2.5 space-y-1.5 transition-colors hover:border-cyan-500/30"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex items-center gap-2 min-w-0">
                                  <button
                                    type="button"
                                    onClick={() => toggleField(idx)}
                                    className="text-muted-foreground hover:text-white transition-colors cursor-pointer"
                                    title="Toggle provenance details"
                                  >
                                    {isExpanded ? (
                                      <ChevronDown className="h-3.5 w-3.5 text-cyan-400" />
                                    ) : (
                                      <ChevronRight className="h-3.5 w-3.5" />
                                    )}
                                  </button>
                                  <span className="text-xs font-semibold text-white truncate">
                                    {formatFieldName(field.field_name)}
                                  </span>
                                  <span className="text-[10px] font-mono text-muted-foreground px-1.5 py-0.2 rounded bg-muted/40 shrink-0">
                                    {field.section_name}
                                  </span>
                                </div>

                                <div className="flex items-center gap-2 shrink-0">
                                  {field.confidence != null ? (
                                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                      {Math.round(field.confidence * 100)}%
                                    </span>
                                  ) : (
                                    <span className="text-[10px] font-mono text-muted-foreground">N/A</span>
                                  )}
                                </div>
                              </div>

                              <div className="pl-5 text-xs">
                                {isNull ? (
                                  <span className="text-muted-foreground italic font-mono text-[11px]">
                                    null (strict null policy)
                                  </span>
                                ) : (
                                  <span className="text-slate-100 font-mono text-[11px] break-all">
                                    {String(field.field_value)}
                                  </span>
                                )}
                              </div>

                              {/* Provenance Details */}
                              {isExpanded && (
                                <div className="mt-2 ml-5 p-2 rounded bg-muted/30 border border-border/30 text-[10px] font-mono text-muted-foreground space-y-1">
                                  <div>
                                    <span className="text-slate-400">Field Key:</span> {field.field_name}
                                  </div>
                                  <div>
                                    <span className="text-slate-400">Source:</span> {field.source || 'gemini'} (Page {field.page_number || 1})
                                  </div>
                                  {field.source_text && (
                                    <div>
                                      <span className="text-slate-400">Source Text Excerpt:</span>
                                      <div className="mt-0.5 p-1.5 rounded bg-background/80 text-slate-300 italic whitespace-pre-wrap">
                                        &quot;{field.source_text}&quot;
                                      </div>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>

                      {/* Line Items Table if invoice line items exist */}
                      {extractionResult.section_data?.line_items?.items?.length > 0 && (
                        <div className="pt-2 border-t border-border/40 space-y-1.5">
                          <div className="text-[11px] font-semibold text-cyan-300 flex items-center gap-1.5">
                            <FileSpreadsheet className="h-3.5 w-3.5" />
                            Extracted Line Items ({extractionResult.section_data.line_items.items.length})
                          </div>
                          <div className="overflow-x-auto rounded border border-border/40 bg-background/40">
                            <table className="w-full text-left text-[11px] font-mono">
                              <thead>
                                <tr className="border-b border-border/40 text-muted-foreground bg-muted/20">
                                  <th className="p-1.5">Description</th>
                                  <th className="p-1.5 text-right">Qty</th>
                                  <th className="p-1.5 text-right">Unit Price</th>
                                  <th className="p-1.5 text-right">Total</th>
                                </tr>
                              </thead>
                              <tbody>
                                {extractionResult.section_data.line_items.items.map((item, i) => (
                                  <tr key={i} className="border-b border-border/20 last:border-0 hover:bg-white/5">
                                    <td className="p-1.5 text-slate-200">{item.description || '—'}</td>
                                    <td className="p-1.5 text-right text-slate-300">{item.quantity ?? '—'}</td>
                                    <td className="p-1.5 text-right text-slate-300">{item.unit_price != null ? `$${item.unit_price}` : '—'}</td>
                                    <td className="p-1.5 text-right font-semibold text-cyan-400">{item.total_amount != null ? `$${item.total_amount}` : '—'}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Validation Results Panel */}
              {validationResult && (
                <div className="rounded-lg border border-emerald-500/30 bg-emerald-950/20 p-3 text-xs font-mono space-y-3">
                  <div className="flex items-center justify-between border-b border-emerald-500/20 pb-2">
                    <div className="flex items-center gap-1.5 text-emerald-400 font-semibold">
                      <ShieldCheck className="h-4 w-4" />
                      <span>Deterministic Validation Summary</span>
                    </div>
                    <Badge
                      variant={validationResult.document_status === "completed" ? "success" : "warning"}
                      className={`text-[10px] font-mono uppercase px-2 py-0.5 ${validationResult.document_status === "completed" ? "bg-emerald-600/20 text-emerald-300 border-emerald-500/30" : "bg-amber-600/20 text-amber-300 border-amber-500/30"}`}
                    >
                      {validationResult.document_status === "completed" ? "Document: Completed" : "Document: Needs Review"}
                    </Badge>
                  </div>

                  {/* Summary Metric Counters */}
                  <div className="grid grid-cols-4 gap-2 text-center">
                    <div className="rounded bg-background/60 p-2 border border-border/40">
                      <div className="text-[10px] text-muted-foreground uppercase">Total Fields</div>
                      <div className="text-sm font-bold text-white">{validationResult.summary?.total_fields ?? 0}</div>
                    </div>
                    <div className="rounded bg-background/60 p-2 border border-emerald-500/30">
                      <div className="text-[10px] text-emerald-400/80 uppercase">Valid</div>
                      <div className="text-sm font-bold text-emerald-400">{validationResult.summary?.valid_count ?? 0}</div>
                    </div>
                    <div className="rounded bg-background/60 p-2 border border-amber-500/30">
                      <div className="text-[10px] text-amber-400/80 uppercase">Needs Review</div>
                      <div className="text-sm font-bold text-amber-400">{validationResult.summary?.needs_review_count ?? 0}</div>
                    </div>
                    <div className="rounded bg-background/60 p-2 border border-rose-500/30">
                      <div className="text-[10px] text-rose-400/80 uppercase">Conflicts</div>
                      <div className="text-sm font-bold text-rose-400">{validationResult.summary?.conflict_count ?? 0}</div>
                    </div>
                  </div>

                  {/* Validation Issues Alert Box if issues exist */}
                  {validationResult.validation_issues?.length > 0 && (
                    <div className="rounded border border-amber-500/30 bg-amber-950/20 p-2.5 space-y-1.5 text-[11px]">
                      <div className="font-semibold text-amber-300 flex items-center gap-1.5">
                        <AlertCircle className="h-3.5 w-3.5" />
                        Issues Detected ({validationResult.validation_issues.length}):
                      </div>
                      <div className="space-y-1">
                        {validationResult.validation_issues.map((issue, idx) => (
                          <div key={idx} className="flex items-start gap-2 bg-background/50 p-1.5 rounded border border-amber-500/20">
                            <span className={`px-1.5 py-0.2 rounded text-[9px] uppercase font-bold shrink-0 ${issue.status === 'conflict' ? 'bg-rose-500/20 text-rose-300' : 'bg-amber-500/20 text-amber-300'}`}>
                              {issue.status}
                            </span>
                            <div className="flex-1">
                              <span className="font-semibold text-slate-200">{formatFieldName(issue.field_name)}:</span>{' '}
                              <span className="text-slate-300">{issue.message}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Validated Fields List (Original vs Normalized) */}
                  <div className="space-y-1.5 pt-1">
                    <div className="text-[11px] font-semibold text-slate-200">
                      Normalized & Validated Fields ({validationResult.fields?.length ?? 0})
                    </div>
                    <div className="max-h-56 overflow-y-auto space-y-1.5 pr-1">
                      {validationResult.fields?.map((field, idx) => {
                        const isExpanded = expandedFields[`val_${field.field_name}_${idx}`];
                        const isConflict = field.validation_status === 'conflict';
                        const isNeedsReview = field.validation_status === 'needs_review';
                        return (
                          <div
                            key={idx}
                            className={`rounded bg-background/70 p-2 border text-[11px] transition-colors ${
                              isConflict
                                ? 'border-rose-500/40 bg-rose-950/10'
                                : isNeedsReview
                                  ? 'border-amber-500/40 bg-amber-950/10'
                                  : 'border-border/40'
                            }`}
                          >
                            <div
                              onClick={() => toggleField(`val_${field.field_name}_${idx}`)}
                              className="flex items-center justify-between gap-2 cursor-pointer select-none"
                            >
                              <div className="flex items-center gap-1.5 min-w-0">
                                {isExpanded ? (
                                  <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                                ) : (
                                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                                )}
                                <span className="font-semibold text-slate-200 truncate">
                                  {formatFieldName(field.field_name)}
                                </span>
                              </div>

                              <div className="flex items-center gap-1.5 shrink-0">
                                <Badge
                                  variant="outline"
                                  className={`text-[9px] uppercase px-1.5 py-0.2 font-bold ${
                                    isConflict
                                      ? 'border-rose-500/50 bg-rose-500/10 text-rose-300'
                                      : isNeedsReview
                                        ? 'border-amber-500/50 bg-amber-500/10 text-amber-300'
                                        : 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                                  }`}
                                >
                                  {field.validation_status || 'VALID'}
                                </Badge>
                                {field.confidence != null && (
                                  <span className="text-[10px] text-muted-foreground">
                                    {Math.round(field.confidence * 100)}%
                                  </span>
                                )}
                              </div>
                            </div>

                            {/* Value Display: Original & Normalized */}
                            <div className="mt-1.5 ml-5 grid grid-cols-2 gap-2 text-[10px] font-mono">
                              <div className="rounded bg-background/60 p-1.5 border border-border/30">
                                <span className="text-muted-foreground block text-[9px] uppercase">Original Value:</span>
                                <span className="text-slate-200 break-all font-medium">
                                  {field.field_value != null ? String(field.field_value) : <span className="text-muted-foreground italic">null</span>}
                                </span>
                              </div>
                              <div className="rounded bg-background/60 p-1.5 border border-border/30">
                                <span className="text-muted-foreground block text-[9px] uppercase">Normalized Value:</span>
                                <span className="text-emerald-300 break-all font-medium">
                                  {field.normalized_value != null ? String(field.normalized_value) : <span className="text-muted-foreground italic">null</span>}
                                </span>
                              </div>
                            </div>

                            {/* Validation Message Callout */}
                            {field.validation_message && (
                              <div className={`mt-1.5 ml-5 p-1.5 rounded text-[10px] flex items-center gap-1.5 border ${
                                isConflict ? 'bg-rose-950/30 text-rose-300 border-rose-500/30' : 'bg-amber-950/30 text-amber-300 border-amber-500/30'
                              }`}>
                                <AlertCircle className="h-3 w-3 shrink-0" />
                                <span>{field.validation_message}</span>
                              </div>
                            )}

                            {/* Expanded Provenance */}
                            {isExpanded && (
                              <div className="mt-2 ml-5 p-2 rounded bg-muted/30 border border-border/30 text-[10px] font-mono text-muted-foreground space-y-1">
                                <div><span className="text-slate-400">Field Key:</span> {field.field_name}</div>
                                <div><span className="text-slate-400">Source:</span> {field.source || 'gemini'} (Page {field.page_number || 1})</div>
                                {field.source_text && (
                                  <div>
                                    <span className="text-slate-400">Source Text Excerpt:</span>
                                    <div className="mt-0.5 p-1.5 rounded bg-background/80 text-slate-300 italic whitespace-pre-wrap">
                                      &quot;{field.source_text}&quot;
                                    </div>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}

              {/* Vision Fallback Error Banner */}
              {visionError && (
                <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-2.5 text-xs text-destructive flex items-center gap-2">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  <span>{visionError}</span>
                </div>
              )}

              {/* Phase 10: Vision Fallback Recovery Panel */}
              {visionResult && (
                <div className="rounded-lg border border-indigo-500/30 bg-indigo-950/20 p-3 text-xs font-mono space-y-2.5">
                  <div className="flex items-center justify-between text-indigo-300 font-semibold border-b border-indigo-500/20 pb-2">
                    <span className="flex items-center gap-1.5 text-indigo-300">
                      <Eye className="h-4 w-4 text-indigo-400" /> Phase 10: Vision Recovery & Fallback
                    </span>
                    <Badge
                      variant="outline"
                      className="text-[10px] uppercase font-mono border-indigo-500/40 text-indigo-300 bg-indigo-500/10"
                    >
                      {visionResult.status}
                    </Badge>
                  </div>

                  {/* Summary Metric Counters */}
                  <div className="grid grid-cols-3 gap-2 py-0.5 text-center">
                    <div className="rounded bg-background/60 p-2 border border-border/40">
                      <div className="text-[10px] text-muted-foreground uppercase">Candidates</div>
                      <div className="text-sm font-bold text-white">{visionResult.candidates_identified ?? 0}</div>
                    </div>
                    <div className="rounded bg-background/60 p-2 border border-emerald-500/30">
                      <div className="text-[10px] text-emerald-400/80 uppercase">Recovered</div>
                      <div className="text-sm font-bold text-emerald-400">{visionResult.fields_recovered ?? 0}</div>
                    </div>
                    <div className="rounded bg-background/60 p-2 border border-rose-500/30">
                      <div className="text-[10px] text-rose-400/80 uppercase">Conflicts</div>
                      <div className="text-sm font-bold text-rose-400">{visionResult.conflicts_detected ?? 0}</div>
                    </div>
                  </div>

                  {/* Fallback Outcomes List */}
                  {visionResult.fallback_fields?.length > 0 ? (
                    <div className="space-y-1.5 pt-1">
                      <div className="text-[11px] font-semibold text-slate-200">
                        Evaluated Fields ({visionResult.fallback_fields.length})
                      </div>
                      <div className="max-h-56 overflow-y-auto space-y-1.5 pr-1">
                        {visionResult.fallback_fields.map((fb, idx) => {
                          const action = fb.action_taken;
                          const isRecovered = action === 'recovered';
                          const isConflict = action === 'conflict';
                          const isAgreed = action === 'agreed';

                          const badgeColor = isRecovered
                            ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                            : isAgreed
                              ? 'border-blue-500/50 bg-blue-500/10 text-blue-300'
                              : isConflict
                                ? 'border-rose-500/50 bg-rose-500/10 text-rose-300'
                                : 'border-amber-500/50 bg-amber-500/10 text-amber-300';

                          return (
                            <div
                              key={idx}
                              className={`rounded bg-background/70 p-2 border text-[11px] space-y-1.5 ${
                                isConflict
                                  ? 'border-rose-500/40 bg-rose-950/10'
                                  : isRecovered
                                    ? 'border-emerald-500/40 bg-emerald-950/10'
                                    : 'border-border/40'
                              }`}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-semibold text-slate-200 truncate">
                                  {formatFieldName(fb.field_name)}
                                </span>
                                <Badge variant="outline" className={`text-[9px] uppercase font-bold px-1.5 py-0.2 ${badgeColor}`}>
                                  {action}
                                </Badge>
                              </div>

                              <div className="grid grid-cols-2 gap-2 text-[10px] font-mono">
                                <div className="rounded bg-background/60 p-1.5 border border-border/30">
                                  <div className="text-[9px] text-muted-foreground uppercase flex justify-between">
                                    <span>OCR Read:</span>
                                    {fb.ocr_confidence != null && <span>{Math.round(fb.ocr_confidence * 100)}%</span>}
                                  </div>
                                  <span className="text-slate-300 break-all">
                                    {fb.ocr_value != null ? String(fb.ocr_value) : <span className="italic text-muted-foreground">null</span>}
                                  </span>
                                </div>
                                <div className="rounded bg-background/60 p-1.5 border border-border/30">
                                  <div className="text-[9px] text-indigo-400 uppercase flex justify-between">
                                    <span>Vision Read:</span>
                                    {fb.vision_confidence != null && <span>{Math.round(fb.vision_confidence * 100)}%</span>}
                                  </div>
                                  <span className="text-indigo-200 break-all font-medium">
                                    {fb.vision_value != null ? String(fb.vision_value) : <span className="italic text-muted-foreground">null</span>}
                                  </span>
                                </div>
                              </div>

                              {fb.reason && (
                                <div className="text-[10px] text-slate-400 italic">
                                  Reason: {fb.reason}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ) : (
                    <div className="text-[11px] text-muted-foreground italic text-center py-1">
                      All fields satisfied confidence thresholds. No targeted vision recovery required.
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

                {uploadedDoc.status !== "preprocessed" && uploadedDoc.status !== "ocr_completed" && uploadedDoc.status !== "classified" && uploadedDoc.status !== "sectioned" && uploadedDoc.status !== "extracted" && !preprocessResult ? (
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
                ) : classificationResult.document_type === "unknown" ? (
                  <Badge variant="outline" className="text-xs gap-1 py-1 px-2.5 border-amber-500/40 text-amber-300">
                    <AlertCircle className="h-3.5 w-3.5 text-amber-400" />
                    Sections & Extraction Skipped (Unknown Type)
                  </Badge>
                ) : !sectionsResult ? (
                  <Button
                    size="sm"
                    onClick={handleDetectSections}
                    disabled={detectingSections}
                    className="text-xs gap-1.5 bg-amber-600 hover:bg-amber-500 text-white shadow-md shadow-amber-500/20 cursor-pointer"
                  >
                    {detectingSections ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Detecting Sections...
                      </>
                    ) : (
                      <>
                        <FolderTree className="h-3.5 w-3.5" />
                        Detect Sections
                      </>
                    )}
                  </Button>
                ) : !extractionResult ? (
                  <Button
                    size="sm"
                    onClick={handleExtractFields}
                    disabled={extracting}
                    className="text-xs gap-1.5 bg-cyan-600 hover:bg-cyan-500 text-white shadow-md shadow-cyan-500/20 cursor-pointer"
                  >
                    {extracting ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Extracting structured information...
                      </>
                    ) : (
                      <>
                        <Sparkles className="h-3.5 w-3.5" />
                        Extract Information
                      </>
                    )}
                  </Button>
                ) : !validationResult ? (
                  <Button
                    size="sm"
                    onClick={handleValidate}
                    disabled={validating}
                    className="text-xs gap-1.5 bg-emerald-600 hover:bg-emerald-500 text-white shadow-md shadow-emerald-500/20 cursor-pointer"
                  >
                    {validating ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Validating deterministic rules...
                      </>
                    ) : (
                      <>
                        <ShieldCheck className="h-3.5 w-3.5" />
                        Normalize & Validate
                      </>
                    )}
                  </Button>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      size="sm"
                      onClick={handleVisionFallback}
                      disabled={recoveringVision || validating}
                      className="text-xs gap-1.5 bg-indigo-600 hover:bg-indigo-500 text-white shadow-md shadow-indigo-500/20 cursor-pointer"
                    >
                      {recoveringVision ? (
                        <>
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          Recovering...
                        </>
                      ) : (
                        <>
                          <Eye className="h-3.5 w-3.5" />
                          Recover Low-Confidence
                        </>
                      )}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleValidate}
                      disabled={validating || recoveringVision}
                      className="text-xs gap-1 border-emerald-500/30 text-emerald-300 hover:bg-emerald-950/30 cursor-pointer"
                    >
                      {validating ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <RotateCcw className="h-3 w-3" />
                      )}
                      Re-validate
                    </Button>
                    <Badge
                      variant={validationResult.document_status === "completed" ? "success" : "warning"}
                      className={`text-xs gap-1 py-1 px-2.5 ${
                        validationResult.document_status === "completed"
                          ? "bg-emerald-600/20 border-emerald-500/40 text-emerald-300"
                          : "bg-amber-600/20 border-amber-500/40 text-amber-300"
                      }`}
                    >
                      {validationResult.document_status === "completed" ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                      ) : (
                        <AlertCircle className="h-3.5 w-3.5 text-amber-400" />
                      )}
                      {validationResult.document_status === "completed" ? "Validation Passed" : "Needs Review"}
                    </Badge>
                  </div>
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
