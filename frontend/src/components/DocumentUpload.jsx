import React, { useState, useRef, useMemo } from 'react';
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
  FolderTree,
  ChevronDown,
  ChevronRight,
  ShieldCheck,
  CheckSquare,
  Eye,
  AlertTriangle,
  ListTodo,
  Calendar,
  Zap,
  Play,
  ArrowRight,
  Filter,
  Ban,
  Search,
  CheckCheck,
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

const KEY_FIELDS = new Set([
  'invoice_number',
  'invoice_date',
  'due_date',
  'total_amount',
  'subtotal',
  'tax_amount',
  'vendor_name',
  'customer_name',
  'full_name',
  'email',
  'phone',
  'start_date',
  'job_title',
  'department',
]);

export default function DocumentUpload({ onUploadSuccess }) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [error, setError] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadedDoc, setUploadedDoc] = useState(null);

  // Pipeline stage state
  const [preprocessing, setPreprocessing] = useState(false);
  const [preprocessResult, setPreprocessResult] = useState(null);

  const [runningOcr, setRunningOcr] = useState(false);
  const [ocrProgressText, setOcrProgressText] = useState('');
  const [ocrResult, setOcrResult] = useState(null);
  const [viewMode, setViewMode] = useState('full');
  const [showRawOcr, setShowRawOcr] = useState(false);

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

  const [generatingInsights, setGeneratingInsights] = useState(false);
  const [summaryResult, setSummaryResult] = useState(null);
  const [actionsResult, setActionsResult] = useState(null);
  const [insightsError, setInsightsError] = useState(null);
  const [actionUpdatingId, setActionUpdatingId] = useState(null);

  // End-to-End Orchestrator state
  const [isProcessingAll, setIsProcessingAll] = useState(false);
  const [processStepText, setProcessStepText] = useState('');

  // Structured Data Filters
  const [fieldSearchFilter, setFieldSearchFilter] = useState('');
  const [fieldStatusFilter, setFieldStatusFilter] = useState('all');

  const inputRef = useRef(null);

  // Consolidated active error to eliminate duplicate error banners
  const activeError = error || validationError || extractionError || sectionsError || visionError || insightsError;

  const validateFile = (file) => {
    if (!file) return false;
    if (file.size > MAX_FILE_SIZE_BYTES) {
      setError(`File is too large (${formatBytes(file.size)}). Maximum size is ${MAX_FILE_SIZE_MB} MB.`);
      return false;
    }
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
    if (e.type === 'dragenter' || e.type === 'dragover') setDragActive(true);
    else if (e.type === 'dragleave') setDragActive(false);
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
      if (onUploadSuccess) onUploadSuccess(result.data);
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
      setUploadedDoc((prev) => ({ ...prev, status: 'preprocessed' }));
    } else {
      setError(result.error || 'Preprocessing failed.');
    }
  };

  const handleRunOcr = async () => {
    if (!uploadedDoc?.id) return;
    setRunningOcr(true);
    setError(null);
    setOcrProgressText('Running OCR...');

    const result = await api.runOcr(uploadedDoc.id);
    setRunningOcr(false);
    setOcrProgressText('');

    if (result.ok && result.data) {
      setOcrResult(result.data);
      setUploadedDoc((prev) => ({ ...prev, status: 'ocr_completed' }));
    } else {
      setError(result.error || 'OCR extraction failed.');
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
      setError(result.error || 'Classification failed.');
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
      setUploadedDoc((prev) => ({ ...prev, status: 'sectioned' }));
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
        setUploadedDoc((prev) => ({ ...prev, status: 'extracted' }));
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
      setUploadedDoc((prev) => ({ ...prev, status: result.data.document_status }));
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

  const handleGenerateInsights = async () => {
    if (!uploadedDoc?.id) return;
    setGeneratingInsights(true);
    setInsightsError(null);

    const result = await api.generateInsights(uploadedDoc.id);
    setGeneratingInsights(false);

    if (result.ok && result.data) {
      setSummaryResult(result.data.summary);
      setActionsResult(result.data.actions);
      if (result.data.document_status) {
        setUploadedDoc((prev) => ({ ...prev, status: result.data.document_status }));
      }
    } else {
      setInsightsError(result.error || 'Failed to generate summary and actions.');
    }
  };

  const handleUpdateActionStatus = async (actionId, newStatus) => {
    if (!actionId || !actionsResult) return;
    setActionUpdatingId(actionId);

    const previousActions = [...actionsResult.actions];
    setActionsResult((prev) => ({
      ...prev,
      actions: prev.actions.map((act) =>
        act.id === actionId ? { ...act, status: newStatus } : act
      ),
    }));

    const result = await api.updateActionStatus(actionId, newStatus);
    setActionUpdatingId(null);

    if (!result.ok) {
      setActionsResult((prev) => ({ ...prev, actions: previousActions }));
      setInsightsError(result.error || 'Failed to update action status.');
    }
  };

  // End-to-End Pipeline Execution
  const handleProcessDocument = async () => {
    if (!uploadedDoc?.id || isProcessingAll) return;
    setIsProcessingAll(true);
    setError(null);
    setSectionsError(null);
    setExtractionError(null);
    setValidationError(null);
    setVisionError(null);
    setInsightsError(null);

    try {
      let currentDoc = uploadedDoc;

      // 1. Preprocess
      if (!preprocessResult && currentDoc.status !== 'preprocessed' && currentDoc.status !== 'ocr_completed' && currentDoc.status !== 'classified') {
        setProcessStepText('Step 1/8: Preprocessing document pages...');
        const preRes = await api.preprocessDocument(currentDoc.id);
        if (!preRes.ok || !preRes.data) {
          setError(preRes.error || 'Preprocessing failed.');
          setIsProcessingAll(false);
          return;
        }
        setPreprocessResult(preRes.data);
        currentDoc = { ...currentDoc, status: 'preprocessed' };
        setUploadedDoc(currentDoc);
      }

      // 2. OCR
      if (!ocrResult) {
        setProcessStepText('Step 2/8: Running layout-aware OCR extraction...');
        const ocrRes = await api.runOcr(currentDoc.id);
        if (!ocrRes.ok || !ocrRes.data) {
          setError(ocrRes.error || 'OCR extraction failed.');
          setIsProcessingAll(false);
          return;
        }
        setOcrResult(ocrRes.data);
        currentDoc = { ...currentDoc, status: 'ocr_completed' };
        setUploadedDoc(currentDoc);
      }

      // 3. Classify
      let currentClass = classificationResult;
      if (!currentClass) {
        setProcessStepText('Step 3/8: Classifying document archetype...');
        const classRes = await api.classifyDocument(currentDoc.id);
        if (!classRes.ok || !classRes.data) {
          setError(classRes.error || 'Classification failed.');
          setIsProcessingAll(false);
          return;
        }
        currentClass = classRes.data;
        setClassificationResult(currentClass);
        currentDoc = {
          ...currentDoc,
          status: 'classified',
          document_type: currentClass.document_type,
        };
        setUploadedDoc(currentDoc);
      }

      // Check Unknown Document Archetype
      if (currentClass.document_type === 'unknown') {
        setProcessStepText('Document archetype is Unknown. Downstream extraction safely skipped.');
        setIsProcessingAll(false);
        return;
      }

      // 4. Detect Sections
      if (!sectionsResult) {
        setProcessStepText('Step 4/8: Detecting logical document sections...');
        const secRes = await api.detectSections(currentDoc.id);
        if (!secRes.ok || !secRes.data) {
          setSectionsError(secRes.error || 'Section detection failed.');
          setIsProcessingAll(false);
          return;
        }
        setSectionsResult(secRes.data);
        currentDoc = { ...currentDoc, status: 'sectioned' };
        setUploadedDoc(currentDoc);
      }

      // 5. Targeted Extraction
      if (!extractionResult) {
        setProcessStepText('Step 5/8: Extracting structured field schemas...');
        const extRes = await api.extractFields(currentDoc.id);
        if (!extRes.ok || !extRes.data) {
          setExtractionError(extRes.error || 'Field extraction failed.');
          setIsProcessingAll(false);
          return;
        }
        setExtractionResult(extRes.data);
        if (extRes.data.status !== 'skipped') {
          currentDoc = { ...currentDoc, status: 'extracted' };
          setUploadedDoc(currentDoc);
        }
      }

      // 6. Normalization & Validation
      setProcessStepText('Step 6/8: Running deterministic normalization & validation...');
      const valRes = await api.validateDocument(currentDoc.id);
      if (valRes.ok && valRes.data) {
        setValidationResult(valRes.data);
        currentDoc = { ...currentDoc, status: valRes.data.document_status };
        setUploadedDoc(currentDoc);
      } else {
        setValidationError(valRes.error || 'Validation failed.');
      }

      // 7. Vision Fallback
      if (!visionResult) {
        setProcessStepText('Step 7/8: Evaluating low-confidence vision recovery...');
        const visRes = await api.runVisionFallback(currentDoc.id);
        if (visRes.ok && visRes.data) {
          setVisionResult(visRes.data);
          if (visRes.data.updated_validation) {
            setValidationResult(visRes.data.updated_validation);
            currentDoc = { ...currentDoc, status: visRes.data.updated_validation.document_status };
            setUploadedDoc(currentDoc);
          }
        }
      }

      // 8. Summary & Actions
      setProcessStepText('Step 8/8: Generating executive summary & operational action items...');
      const insRes = await api.generateInsights(currentDoc.id);
      if (insRes.ok && insRes.data) {
        setSummaryResult(insRes.data.summary);
        setActionsResult(insRes.data.actions);
        if (insRes.data.document_status) {
          setUploadedDoc((prev) => ({ ...prev, status: insRes.data.document_status }));
        }
      } else {
        setInsightsError(insRes.error || 'Insights generation failed.');
      }

    } catch (err) {
      setError(err.message || 'Error occurred during end-to-end processing.');
    } finally {
      setIsProcessingAll(false);
      setProcessStepText('');
    }
  };

  const toggleSection = (idx) => {
    setExpandedSections((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const toggleField = (key) => {
    setExpandedFields((prev) => ({ ...prev, [key]: !prev[key] }));
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
    setSummaryResult(null);
    setActionsResult(null);
    setRunningOcr(false);
    setClassifying(false);
    setDetectingSections(false);
    setExtracting(false);
    setValidating(false);
    setRecoveringVision(false);
    setGeneratingInsights(false);
    setIsProcessingAll(false);
    setProcessStepText('');
    setError(null);
    setSectionsError(null);
    setExtractionError(null);
    setValidationError(null);
    setVisionError(null);
    setInsightsError(null);
    setActionUpdatingId(null);
    setExpandedSections({});
    setExpandedFields({});
    setFieldSearchFilter('');
    setFieldStatusFilter('all');
    setShowRawOcr(false);
    if (inputRef.current) inputRef.current.value = '';
  };

  // Pipeline Stepper 11 Stages Definition
  const isUnknownArchetype = classificationResult?.document_type === 'unknown';

  const pipelineStages = useMemo(() => [
    {
      id: 'upload',
      label: 'Upload',
      status: uploadedDoc ? 'completed' : 'pending',
    },
    {
      id: 'preprocess',
      label: 'Preprocess',
      status: preprocessing
        ? 'active'
        : preprocessResult || ocrResult || classificationResult
          ? 'completed'
          : 'pending',
    },
    {
      id: 'ocr',
      label: 'OCR',
      status: runningOcr
        ? 'active'
        : ocrResult
          ? 'completed'
          : 'pending',
    },
    {
      id: 'classify',
      label: 'Classify',
      status: classifying
        ? 'active'
        : classificationResult
          ? 'completed'
          : 'pending',
    },
    {
      id: 'sections',
      label: 'Sections',
      status: isUnknownArchetype
        ? 'skipped'
        : detectingSections
          ? 'active'
          : sectionsResult
            ? 'completed'
            : 'pending',
    },
    {
      id: 'extract',
      label: 'Extract',
      status: isUnknownArchetype || extractionResult?.status === 'skipped'
        ? 'skipped'
        : extracting
          ? 'active'
          : extractionResult
            ? 'completed'
            : 'pending',
    },
    {
      id: 'normalize',
      label: 'Normalize',
      status: isUnknownArchetype || extractionResult?.status === 'skipped'
        ? 'skipped'
        : validating
          ? 'active'
          : validationResult
            ? 'completed'
            : 'pending',
    },
    {
      id: 'validate',
      label: 'Validate',
      status: isUnknownArchetype || extractionResult?.status === 'skipped'
        ? 'skipped'
        : validating
          ? 'active'
          : validationResult
            ? 'completed'
            : 'pending',
    },
    {
      id: 'vision_fallback',
      label: 'Vision Fallback',
      status: isUnknownArchetype || extractionResult?.status === 'skipped'
        ? 'skipped'
        : recoveringVision
          ? 'active'
          : visionResult
            ? 'completed'
            : 'pending',
    },
    {
      id: 'summary',
      label: 'Summary',
      status: isUnknownArchetype || summaryResult?.status === 'skipped'
        ? 'skipped'
        : generatingInsights
          ? 'active'
          : summaryResult
            ? 'completed'
            : 'pending',
    },
    {
      id: 'actions',
      label: 'Actions',
      status: isUnknownArchetype || actionsResult?.status === 'skipped'
        ? 'skipped'
        : generatingInsights
          ? 'active'
          : actionsResult
            ? 'completed'
            : 'pending',
    },
  ], [
    uploadedDoc,
    preprocessing,
    preprocessResult,
    runningOcr,
    ocrResult,
    classifying,
    classificationResult,
    isUnknownArchetype,
    detectingSections,
    sectionsResult,
    extracting,
    extractionResult,
    validating,
    validationResult,
    recoveringVision,
    visionResult,
    generatingInsights,
    summaryResult,
    actionsResult,
  ]);

  // Filtered Structured Fields for scanning
  const rawFieldsList = validationResult?.fields || extractionResult?.fields || [];

  const filteredFields = useMemo(() => {
    return rawFieldsList.filter((f) => {
      const matchSearch =
        !fieldSearchFilter ||
        f.field_name.toLowerCase().includes(fieldSearchFilter.toLowerCase()) ||
        String(f.field_value ?? '').toLowerCase().includes(fieldSearchFilter.toLowerCase()) ||
        String(f.normalized_value ?? '').toLowerCase().includes(fieldSearchFilter.toLowerCase());

      if (!matchSearch) return false;

      if (fieldStatusFilter === 'valid') return f.validation_status === 'valid' || f.validation_status === 'VALID';
      if (fieldStatusFilter === 'review') return f.validation_status === 'needs_review';
      if (fieldStatusFilter === 'conflict') return f.validation_status === 'conflict';
      return true;
    });
  }, [rawFieldsList, fieldSearchFilter, fieldStatusFilter]);

  // Actual API Overview Metrics (Requirement 3: Zero fake numbers)
  const overviewDocType =
    classificationResult?.document_type === 'invoice'
      ? 'Invoice'
      : classificationResult?.document_type === 'onboarding_form'
        ? 'Onboarding Form'
        : classificationResult?.document_type === 'unknown'
          ? 'Unknown'
          : uploadedDoc?.document_type
            ? formatSectionTitle(uploadedDoc.document_type)
            : 'Pending Classification';

  const overviewStatus = uploadedDoc?.status ? uploadedDoc.status.replace('_', ' ') : 'uploaded';

  const overviewPages =
    preprocessResult?.page_count ||
    ocrResult?.page_count ||
    uploadedDoc?.page_count ||
    1;

  const overviewOcrConfidence =
    ocrResult?.metadata?.average_confidence != null
      ? `${ocrResult.metadata.average_confidence}%`
      : ocrResult
        ? 'Completed'
        : 'Pending';

  const overviewFieldCount =
    isUnknownArchetype
      ? '0 (Skipped)'
      : validationResult?.fields?.length ?? extractionResult?.fields?.length ?? 0;

  const overviewValidationStatus = isUnknownArchetype
    ? 'Skipped'
    : validationResult
      ? validationResult.document_status === 'completed'
        ? 'Valid'
        : validationResult.summary?.conflict_count > 0
          ? 'Conflicts'
          : 'Needs Review'
      : 'Pending';

  const overviewActionCount = isUnknownArchetype
    ? '0 (Skipped)'
    : actionsResult?.total_actions ?? actionsResult?.actions?.length ?? 0;

  return (
    <Card className={`w-full mx-auto border-border/60 bg-card/60 backdrop-blur-xl shadow-2xl text-left transition-all duration-300 ${uploadedDoc ? 'max-w-6xl' : 'max-w-xl'}`}>
      <CardHeader className="pb-3 border-b border-border/40">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 border border-primary/20 text-primary">
              <UploadCloud className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-base text-white flex items-center gap-2">
                Document-to-Action Dashboard
                {uploadedDoc && (
                  <Badge variant="outline" className="text-[11px] font-mono border-primary/30 text-primary bg-primary/10">
                    Live Session
                  </Badge>
                )}
              </CardTitle>
              <CardDescription className="text-xs text-muted-foreground">
                {uploadedDoc
                  ? `Active document inspection & execution • ID: ${uploadedDoc.id}`
                  : 'Upload PDF, JPG, or PNG files up to 10 MB for end-to-end processing'}
              </CardDescription>
            </div>
          </div>

          <Badge variant="outline" className="text-[11px] font-mono border-border/50 text-muted-foreground">
            Automated Pipeline
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="pt-5 space-y-6">
        {/* Consolidated Error Banner */}
        {activeError && (
          <div className="flex items-start gap-2.5 rounded-lg border border-rose-500/30 bg-rose-950/25 p-3.5 text-xs text-rose-300">
            <AlertCircle className="h-4 w-4 text-rose-400 shrink-0 mt-0.5" />
            <div className="flex-1 font-medium">{activeError}</div>
          </div>
        )}

        {/* ============================================================ */}
        {/* STATE 1: ACTIVE DOCUMENT DASHBOARD                          */}
        {/* ============================================================ */}
        {uploadedDoc ? (
          <div className="space-y-5">
            {/* 1. DOCUMENT HEADER & META BAR */}
            <div className="rounded-xl border border-border/60 bg-background/50 p-4 space-y-3">
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                {/* File info */}
                <div className="flex items-start gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary/10 border border-primary/20 shrink-0">
                    {uploadedDoc.mime_type === 'application/pdf' ? (
                      <FileText className="h-6 w-6 text-red-400" />
                    ) : (
                      <ImageIcon className="h-6 w-6 text-blue-400" />
                    )}
                  </div>
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-base font-bold text-white break-all">
                        {uploadedDoc.filename}
                      </h3>
                      <span className={`text-[10px] px-2 py-0.5 rounded border font-semibold ${getFileTypeBadge(uploadedDoc.filename, uploadedDoc.mime_type).color}`}>
                        {getFileTypeBadge(uploadedDoc.filename, uploadedDoc.mime_type).label}
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span>{formatBytes(uploadedDoc.file_size)}</span>
                      <span>•</span>
                      <span className="font-mono text-slate-300">ID: {uploadedDoc.id.slice(0, 8)}...</span>
                      {uploadedDoc.storage_path && (
                        <>
                          <span>•</span>
                          <span className="truncate max-w-[200px] text-slate-400">Path: {uploadedDoc.storage_path}</span>
                        </>
                      )}
                    </div>
                  </div>
                </div>

                {/* Primary Dashboard Actions */}
                <div className="flex flex-wrap items-center gap-2 shrink-0">
                  {/* END-TO-END PROCESS DOCUMENT BUTTON */}
                  <Button
                    size="sm"
                    onClick={handleProcessDocument}
                    disabled={isProcessingAll}
                    className="text-xs font-semibold gap-1.5 bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white shadow-lg shadow-indigo-500/25 cursor-pointer"
                  >
                    {isProcessingAll ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        <span>Processing Pipeline...</span>
                      </>
                    ) : (
                      <>
                        <Zap className="h-3.5 w-3.5 fill-amber-300 text-amber-300" />
                        <span>Process Document</span>
                      </>
                    )}
                  </Button>

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
                        Preview
                      </a>
                    </Button>
                  )}

                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleReset}
                    disabled={isProcessingAll}
                    className="text-xs gap-1.5 text-muted-foreground hover:text-white"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    Reset
                  </Button>
                </div>
              </div>

              {/* End-to-End Live Processing Indicator */}
              {isProcessingAll && processStepText && (
                <div className="flex items-center gap-2.5 rounded-lg border border-indigo-500/30 bg-indigo-950/20 p-2.5 text-xs text-indigo-300 font-mono">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-400 shrink-0" />
                  <span className="font-semibold">{processStepText}</span>
                </div>
              )}
            </div>

            {/* 2. PIPELINE STEPPER: 11 STAGES */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold text-slate-300">
                <span className="flex items-center gap-1.5 text-primary">
                  <Layers className="h-3.5 w-3.5" /> End-to-End Pipeline Workflow
                </span>
                <span className="text-[11px] font-mono text-muted-foreground">
                  11 Execution Stages
                </span>
              </div>

              <div className="rounded-xl border border-border/50 bg-background/50 p-3 overflow-x-auto">
                <div className="flex items-center justify-between min-w-[760px] gap-1 text-[11px] font-mono">
                  {pipelineStages.map((stage, idx) => {
                    const isLast = idx === pipelineStages.length - 1;
                    const isDone = stage.status === 'completed';
                    const isActive = stage.status === 'active';
                    const isSkipped = stage.status === 'skipped';

                    return (
                      <React.Fragment key={stage.id}>
                        <div
                          className={`flex items-center gap-1.5 px-2 py-1 rounded-md transition-all shrink-0 ${
                            isDone
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                              : isActive
                                ? 'bg-primary/15 text-primary border border-primary/30 animate-pulse font-bold'
                                : isSkipped
                                  ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                                  : 'bg-muted/30 text-muted-foreground/70 border border-border/30'
                          }`}
                        >
                          {isDone ? (
                            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                          ) : isActive ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                          ) : isSkipped ? (
                            <Ban className="h-3.5 w-3.5 text-amber-400" />
                          ) : (
                            <span className="h-2 w-2 rounded-full bg-slate-600" />
                          )}
                          <span>{stage.label}</span>
                        </div>

                        {!isLast && (
                          <span className="text-muted-foreground/40 shrink-0 select-none">
                            →
                          </span>
                        )}
                      </React.Fragment>
                    );
                  })}
                </div>
              </div>

              {/* STREAMLINED STAGE ACTION CONTROLS */}
              <div className="flex flex-wrap items-center justify-between gap-2 pt-1 px-1">
                <span className="text-[11px] font-medium text-muted-foreground">
                  Individual Controls:
                </span>
                <div className="flex flex-wrap items-center gap-1.5">
                  {!preprocessResult && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handlePreprocess}
                      disabled={preprocessing || isProcessingAll}
                      className="text-xs h-7 px-2.5 gap-1.5"
                    >
                      {preprocessing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Layers className="h-3 w-3 text-indigo-400" />}
                      Preprocess
                    </Button>
                  )}

                  {!ocrResult && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleRunOcr}
                      disabled={runningOcr || isProcessingAll}
                      className="text-xs h-7 px-2.5 gap-1.5"
                    >
                      {runningOcr ? <Loader2 className="h-3 w-3 animate-spin" /> : <ScanText className="h-3 w-3 text-blue-400" />}
                      Run OCR
                    </Button>
                  )}

                  {!classificationResult && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleClassify}
                      disabled={classifying || isProcessingAll}
                      className="text-xs h-7 px-2.5 gap-1.5"
                    >
                      {classifying ? <Loader2 className="h-3 w-3 animate-spin" /> : <Brain className="h-3 w-3 text-purple-400" />}
                      Classify
                    </Button>
                  )}

                  {!isUnknownArchetype && !sectionsResult && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleDetectSections}
                      disabled={detectingSections || isProcessingAll}
                      className="text-xs h-7 px-2.5 gap-1.5"
                    >
                      {detectingSections ? <Loader2 className="h-3 w-3 animate-spin" /> : <FolderTree className="h-3 w-3 text-amber-400" />}
                      Sections
                    </Button>
                  )}

                  {!isUnknownArchetype && !extractionResult && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleExtractFields}
                      disabled={extracting || isProcessingAll}
                      className="text-xs h-7 px-2.5 gap-1.5"
                    >
                      {extracting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3 text-cyan-400" />}
                      Extract
                    </Button>
                  )}

                  {!isUnknownArchetype && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleValidate}
                      disabled={validating || isProcessingAll}
                      className="text-xs h-7 px-2.5 gap-1.5"
                    >
                      {validating ? <Loader2 className="h-3 w-3 animate-spin" /> : <ShieldCheck className="h-3 w-3 text-emerald-400" />}
                      {validationResult ? 'Re-Validate' : 'Validate'}
                    </Button>
                  )}

                  {!isUnknownArchetype && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleVisionFallback}
                      disabled={recoveringVision || isProcessingAll}
                      className="text-xs h-7 px-2.5 gap-1.5"
                    >
                      {recoveringVision ? <Loader2 className="h-3 w-3 animate-spin" /> : <Eye className="h-3 w-3 text-indigo-400" />}
                      Vision Check
                    </Button>
                  )}

                  {!isUnknownArchetype && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleGenerateInsights}
                      disabled={generatingInsights || isProcessingAll}
                      className="text-xs h-7 px-2.5 gap-1.5"
                    >
                      {generatingInsights ? <Loader2 className="h-3 w-3 animate-spin" /> : <ListTodo className="h-3 w-3 text-purple-400" />}
                      {summaryResult && actionsResult ? 'Regenerate Insights' : 'Summary & Actions'}
                    </Button>
                  )}
                </div>
              </div>
            </div>

            {/* 3. DOCUMENT OVERVIEW: 7 ACTUAL METRICS (Requirement 3) */}
            <div className="space-y-2">
              <div className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                <FileCheck className="h-3.5 w-3.5 text-primary" /> Document Overview
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2.5 text-center font-mono">
                {/* 1. Document Type */}
                <div className="rounded-lg bg-background/60 p-2.5 border border-border/50">
                  <div className="text-[10px] text-muted-foreground uppercase">Doc Type</div>
                  <div className="text-xs font-bold text-white capitalize truncate mt-0.5" title={overviewDocType}>
                    {overviewDocType}
                  </div>
                </div>

                {/* 2. Status */}
                <div className="rounded-lg bg-background/60 p-2.5 border border-border/50">
                  <div className="text-[10px] text-muted-foreground uppercase">Status</div>
                  <div className="text-xs font-bold text-primary capitalize truncate mt-0.5" title={overviewStatus}>
                    {overviewStatus}
                  </div>
                </div>

                {/* 3. Pages */}
                <div className="rounded-lg bg-background/60 p-2.5 border border-border/50">
                  <div className="text-[10px] text-muted-foreground uppercase">Pages</div>
                  <div className="text-sm font-bold text-white mt-0.5">{overviewPages}</div>
                </div>

                {/* 4. OCR Confidence */}
                <div className="rounded-lg bg-background/60 p-2.5 border border-border/50">
                  <div className="text-[10px] text-muted-foreground uppercase">OCR Conf.</div>
                  <div className="text-sm font-bold text-emerald-400 mt-0.5">{overviewOcrConfidence}</div>
                </div>

                {/* 5. Extracted Fields */}
                <div className="rounded-lg bg-background/60 p-2.5 border border-border/50">
                  <div className="text-[10px] text-muted-foreground uppercase">Fields</div>
                  <div className="text-sm font-bold text-cyan-300 mt-0.5">{overviewFieldCount}</div>
                </div>

                {/* 6. Validation Status */}
                <div className="rounded-lg bg-background/60 p-2.5 border border-border/50">
                  <div className="text-[10px] text-muted-foreground uppercase">Validation</div>
                  <div className={`text-xs font-bold mt-0.5 truncate ${
                    overviewValidationStatus === 'Valid'
                      ? 'text-emerald-400'
                      : overviewValidationStatus === 'Conflicts'
                        ? 'text-rose-400'
                        : overviewValidationStatus === 'Needs Review'
                          ? 'text-amber-400'
                          : 'text-muted-foreground'
                  }`}>
                    {overviewValidationStatus}
                  </div>
                </div>

                {/* 7. Action Count */}
                <div className="rounded-lg bg-background/60 p-2.5 border border-border/50">
                  <div className="text-[10px] text-muted-foreground uppercase">Actions</div>
                  <div className="text-sm font-bold text-amber-300 mt-0.5">{overviewActionCount}</div>
                </div>
              </div>
            </div>

            {/* UNKNOWN DOCUMENT NOTICE (Requirement 2 & 12) */}
            {isUnknownArchetype && (
              <div className="rounded-xl border border-amber-500/40 bg-amber-950/20 p-4 space-y-2 text-left">
                <div className="flex items-center gap-2 text-amber-300 font-bold text-sm">
                  <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
                  <span>Document Archetype Evaluation: Unsupported / Unknown</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 pt-1 text-xs font-mono">
                  <div className="rounded bg-background/70 p-2 border border-amber-500/30">
                    <span className="text-muted-foreground block text-[10px] uppercase">Classification:</span>
                    <span className="text-amber-300 font-bold">Unknown</span>
                  </div>
                  <div className="rounded bg-background/70 p-2 border border-amber-500/30">
                    <span className="text-muted-foreground block text-[10px] uppercase">Reason:</span>
                    <span className="text-slate-200">Unsupported document type</span>
                  </div>
                  <div className="rounded bg-background/70 p-2 border border-amber-500/30">
                    <span className="text-muted-foreground block text-[10px] uppercase">Sections & Extraction:</span>
                    <span className="text-amber-400 font-semibold">Skipped</span>
                  </div>
                </div>
                <p className="text-xs text-amber-200/80 leading-relaxed pt-1">
                  This document does not match recognized structured schemas (Invoices or Onboarding Forms).
                  In accordance with the pipeline safety policy, sections, field extraction, validation, and insights
                  were safely skipped to prevent hallucinated data.
                </p>
              </div>
            )}

            {/* MAIN DASHBOARD CONTENT GRID (Left: Data & Validation, Right: Summary & Actions) */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
              {/* LEFT COLUMN: STRUCTURED DATA & VALIDATION (7 COLS ON DESKTOP) */}
              <div className="lg:col-span-7 space-y-6">
                {/* 4. STRUCTURED DATA VIEW (Requirement 4) */}
                <div className="rounded-xl border border-border/60 bg-background/50 p-4 space-y-4">
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-b border-border/40 pb-3">
                    <div className="flex items-center gap-2">
                      <Sparkles className="h-4 w-4 text-cyan-400" />
                      <h4 className="text-sm font-bold text-white">Structured Data View</h4>
                      <Badge variant="outline" className="text-[11px] font-mono border-cyan-500/30 text-cyan-300 bg-cyan-500/10">
                        {filteredFields.length} / {rawFieldsList.length} Fields
                      </Badge>
                    </div>

                    {/* Quick Search & Filters */}
                    {rawFieldsList.length > 0 && (
                      <div className="flex items-center gap-1.5">
                        <div className="relative">
                          <Search className="h-3 w-3 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
                          <input
                            type="text"
                            placeholder="Filter field..."
                            value={fieldSearchFilter}
                            onChange={(e) => setFieldSearchFilter(e.target.value)}
                            className="text-[11px] font-mono pl-6 pr-2 py-1 rounded border border-border/50 bg-background text-slate-200 placeholder:text-muted-foreground w-28 sm:w-36 focus:outline-none focus:border-primary"
                          />
                        </div>
                        <select
                          value={fieldStatusFilter}
                          onChange={(e) => setFieldStatusFilter(e.target.value)}
                          className="text-[11px] font-mono px-2 py-1 rounded border border-border/50 bg-background text-slate-300 focus:outline-none"
                        >
                          <option value="all">All</option>
                          <option value="valid">Valid</option>
                          <option value="review">Needs Review</option>
                          <option value="conflict">Conflicts</option>
                        </select>
                      </div>
                    )}
                  </div>

                  {/* Empty state or fields list */}
                  {rawFieldsList.length === 0 ? (
                    <div className="rounded-lg bg-card/40 border border-border/40 p-6 text-center text-xs text-muted-foreground space-y-1">
                      <Sparkles className="h-6 w-6 text-muted-foreground mx-auto mb-1 opacity-50" />
                      <div>No structured fields extracted yet.</div>
                      <div className="text-[11px]">
                        {isUnknownArchetype
                          ? 'Extraction skipped for unknown document archetypes.'
                          : 'Run targeted extraction or click "Process Document" to populate fields.'}
                      </div>
                    </div>
                  ) : filteredFields.length === 0 ? (
                    <div className="rounded-lg bg-card/40 border border-border/40 p-4 text-center text-xs text-muted-foreground">
                      No fields match filter &quot;{fieldSearchFilter}&quot;
                    </div>
                  ) : (
                    <div className="space-y-2.5 max-h-[520px] overflow-y-auto pr-1">
                      {filteredFields.map((field, idx) => {
                        const fieldKey = `fld_${field.field_name}_${idx}`;
                        const isExpanded = !!expandedFields[fieldKey];
                        const isKeyField = KEY_FIELDS.has(field.field_name.toLowerCase());
                        const isConflict = field.validation_status === 'conflict';
                        const isNeedsReview = field.validation_status === 'needs_review';
                        const isValid = field.validation_status === 'valid' || field.validation_status === 'VALID';
                        const displayVal = field.normalized_value ?? field.field_value;
                        const isNull = displayVal === null || displayVal === undefined || String(displayVal).trim() === '';

                        return (
                          <div
                            key={fieldKey}
                            className={`rounded-lg border p-3 text-xs space-y-2 transition-all ${
                              isConflict
                                ? 'border-rose-500/50 bg-rose-950/15'
                                : isNeedsReview
                                  ? 'border-amber-500/40 bg-amber-950/15'
                                  : isKeyField
                                    ? 'border-cyan-500/40 bg-cyan-950/10'
                                    : 'border-border/50 bg-background/60 hover:border-border'
                            }`}
                          >
                            <div className="flex items-start justify-between gap-2">
                              {/* Field Name & Section */}
                              <div className="flex items-center gap-1.5 min-w-0">
                                <button
                                  type="button"
                                  onClick={() => toggleField(fieldKey)}
                                  className="text-muted-foreground hover:text-white transition-colors cursor-pointer p-0.5"
                                  title="Toggle provenance details"
                                >
                                  {isExpanded ? (
                                    <ChevronDown className="h-3.5 w-3.5 text-primary" />
                                  ) : (
                                    <ChevronRight className="h-3.5 w-3.5" />
                                  )}
                                </button>
                                <span className={`font-semibold text-white truncate ${isKeyField ? 'text-cyan-200' : ''}`}>
                                  {formatFieldName(field.field_name)}
                                </span>
                                {field.section_name && (
                                  <span className="text-[10px] font-mono text-muted-foreground px-1.5 py-0.2 rounded bg-muted/40 shrink-0 hidden sm:inline">
                                    {field.section_name}
                                  </span>
                                )}
                              </div>

                              {/* Confidence, Source & Validation Status Badges */}
                              <div className="flex items-center gap-1.5 shrink-0">
                                {/* Validation Status */}
                                <Badge
                                  variant="outline"
                                  className={`text-[9px] uppercase px-1.5 py-0.2 font-bold ${
                                    isConflict
                                      ? 'border-rose-500/50 bg-rose-500/10 text-rose-300'
                                      : isNeedsReview
                                        ? 'border-amber-500/50 bg-amber-500/10 text-amber-300'
                                        : isValid
                                          ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                                          : 'border-border/60 text-muted-foreground'
                                  }`}
                                >
                                  {field.validation_status ? field.validation_status.toUpperCase() : 'EXTRACTED'}
                                </Badge>

                                {/* Confidence Score */}
                                {field.confidence != null && (
                                  <span className={`text-[10px] font-mono px-1.5 py-0.2 rounded border ${
                                    field.confidence >= 0.8
                                      ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                                      : 'border-amber-500/30 bg-amber-500/10 text-amber-300'
                                  }`}>
                                    {Math.round(field.confidence * 100)}%
                                  </span>
                                )}
                              </div>
                            </div>

                            {/* Value Display Row */}
                            <div className="pl-5 text-[11px] font-mono flex items-baseline justify-between gap-2">
                              <div className="flex-1 break-all">
                                {isNull ? (
                                  <span className="text-muted-foreground italic">
                                    null (strict null policy)
                                  </span>
                                ) : (
                                  <span className="text-slate-100 font-medium">
                                    {String(displayVal)}
                                  </span>
                                )}
                              </div>

                              {/* Source badge */}
                              <span className="text-[10px] text-muted-foreground capitalize shrink-0">
                                {field.source || 'gemini'} (P{field.page_number || 1})
                              </span>
                            </div>

                            {/* Validation message if issue detected */}
                            {field.validation_message && (
                              <div className={`ml-5 p-1.5 rounded text-[11px] flex items-center gap-1.5 border ${
                                isConflict
                                  ? 'bg-rose-950/30 text-rose-300 border-rose-500/30'
                                  : 'bg-amber-950/30 text-amber-300 border-amber-500/30'
                              }`}>
                                <AlertCircle className="h-3 w-3 shrink-0" />
                                <span>{field.validation_message}</span>
                              </div>
                            )}

                            {/* Expandable Provenance Detail */}
                            {isExpanded && (
                              <div className="mt-2 ml-5 p-2 rounded bg-muted/30 border border-border/30 text-[10px] font-mono text-muted-foreground space-y-1">
                                <div><span className="text-slate-400">Canonical Key:</span> {field.field_name}</div>
                                <div><span className="text-slate-400">Source:</span> {field.source || 'gemini'} (Page {field.page_number || 1})</div>
                                {field.field_value != null && field.normalized_value != null && field.field_value !== field.normalized_value && (
                                  <div>
                                    <span className="text-slate-400">Raw OCR/AI:</span> {String(field.field_value)} → <span className="text-emerald-400 font-semibold">Normalized:</span> {String(field.normalized_value)}
                                  </div>
                                )}
                                {field.source_text && (
                                  <div className="pt-1">
                                    <span className="text-slate-400">Grounded Source Text Excerpt:</span>
                                    <div className="mt-0.5 p-1.5 rounded bg-background/80 text-slate-300 italic whitespace-pre-wrap select-text">
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
                  )}

                  {/* Line Items Table (if invoice line items exist) */}
                  {extractionResult?.section_data?.line_items?.items?.length > 0 && (
                    <div className="pt-3 border-t border-border/40 space-y-2">
                      <div className="text-xs font-semibold text-cyan-300 flex items-center gap-1.5">
                        <FileSpreadsheet className="h-3.5 w-3.5" />
                        Line Items Breakdown ({extractionResult.section_data.line_items.items.length})
                      </div>
                      <div className="overflow-x-auto rounded-lg border border-border/40 bg-background/40">
                        <table className="w-full text-left text-[11px] font-mono">
                          <thead>
                            <tr className="border-b border-border/40 text-muted-foreground bg-muted/20">
                              <th className="p-2">Description</th>
                              <th className="p-2 text-right">Qty</th>
                              <th className="p-2 text-right">Unit Price</th>
                              <th className="p-2 text-right">Total</th>
                            </tr>
                          </thead>
                          <tbody>
                            {extractionResult.section_data.line_items.items.map((item, i) => (
                              <tr key={i} className="border-b border-border/20 last:border-0 hover:bg-white/5">
                                <td className="p-2 text-slate-200">{item.description || '—'}</td>
                                <td className="p-2 text-right text-slate-300">{item.quantity ?? '—'}</td>
                                <td className="p-2 text-right text-slate-300">{item.unit_price != null ? `$${item.unit_price}` : '—'}</td>
                                <td className="p-2 text-right font-semibold text-cyan-400">{item.total_amount != null ? `$${item.total_amount}` : '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>

                {/* 7. VALIDATION SUMMARY & MESSAGES (Requirement 7: No synthetic score) */}
                <div className="rounded-xl border border-border/60 bg-background/50 p-4 space-y-3">
                  <div className="flex items-center justify-between border-b border-border/40 pb-3">
                    <div className="flex items-center gap-2">
                      <ShieldCheck className="h-4 w-4 text-emerald-400" />
                      <h4 className="text-sm font-bold text-white">Validation</h4>
                    </div>
                    {validationResult && (
                      <Badge
                        variant="outline"
                        className={`text-[10px] font-mono uppercase px-2 py-0.5 ${
                          validationResult.document_status === 'completed'
                            ? 'bg-emerald-600/20 text-emerald-300 border-emerald-500/30'
                            : 'bg-amber-600/20 text-amber-300 border-amber-500/30'
                        }`}
                      >
                        {validationResult.document_status === 'completed' ? 'Valid' : 'Needs Review'}
                      </Badge>
                    )}
                  </div>

                  {validationResult ? (
                    <div className="space-y-3">
                      {/* Compact Validation Summary: Valid, Needs Review, Conflicts */}
                      <div className="grid grid-cols-3 gap-2 text-center font-mono">
                        <div className="rounded-lg bg-background/60 p-2.5 border border-emerald-500/30">
                          <div className="text-[10px] text-emerald-400/80 uppercase font-semibold">Valid</div>
                          <div className="text-base font-bold text-emerald-400">
                            {validationResult.summary?.valid_count ?? 0}
                          </div>
                        </div>
                        <div className="rounded-lg bg-background/60 p-2.5 border border-amber-500/30">
                          <div className="text-[10px] text-amber-400/80 uppercase font-semibold">Needs Review</div>
                          <div className="text-base font-bold text-amber-400">
                            {validationResult.summary?.needs_review_count ?? 0}
                          </div>
                        </div>
                        <div className="rounded-lg bg-background/60 p-2.5 border border-rose-500/30">
                          <div className="text-[10px] text-rose-400/80 uppercase font-semibold">Conflicts</div>
                          <div className="text-base font-bold text-rose-400">
                            {validationResult.summary?.conflict_count ?? 0}
                          </div>
                        </div>
                      </div>

                      {/* Relevant Validation Messages */}
                      {validationResult.validation_issues?.length > 0 ? (
                        <div className="rounded-lg border border-amber-500/30 bg-amber-950/20 p-3 space-y-2 text-xs">
                          <div className="font-semibold text-amber-300 flex items-center gap-1.5">
                            <AlertCircle className="h-3.5 w-3.5" />
                            Validation Issues ({validationResult.validation_issues.length}):
                          </div>
                          <div className="space-y-1.5">
                            {validationResult.validation_issues.map((issue, idx) => (
                              <div key={idx} className="flex items-start gap-2 bg-background/70 p-2 rounded border border-amber-500/20">
                                <span className={`px-1.5 py-0.2 rounded text-[9px] uppercase font-bold shrink-0 ${
                                  issue.status === 'conflict' ? 'bg-rose-500/20 text-rose-300' : 'bg-amber-500/20 text-amber-300'
                                }`}>
                                  {issue.status}
                                </span>
                                <div className="flex-1 text-[11px]">
                                  <span className="font-semibold text-slate-200">{formatFieldName(issue.field_name)}:</span>{' '}
                                  <span className="text-slate-300">{issue.message}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : (
                        <div className="rounded-lg bg-emerald-950/20 border border-emerald-500/30 p-2.5 text-xs text-emerald-300 flex items-center gap-2">
                          <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                          <span>All deterministic business rules, arithmetic checks, and required field constraints passed.</span>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="text-xs text-muted-foreground italic py-2 text-center">
                      Deterministic validation not yet executed. Click &quot;Validate&quot; or &quot;Process Document&quot;.
                    </div>
                  )}
                </div>

                {/* 8. VISION FALLBACK PANEL (Requirement 8) */}
                <div className="rounded-xl border border-border/60 bg-background/50 p-4 space-y-3">
                  <div className="flex items-center justify-between border-b border-border/40 pb-3">
                    <div className="flex items-center gap-2">
                      <Eye className="h-4 w-4 text-indigo-400" />
                      <h4 className="text-sm font-bold text-white">Vision Fallback</h4>
                    </div>
                    {visionResult && (
                      <Badge variant="outline" className="text-[10px] uppercase font-mono border-indigo-500/40 text-indigo-300 bg-indigo-500/10">
                        {visionResult.status}
                      </Badge>
                    )}
                  </div>

                  {visionResult ? (
                    visionResult.fallback_fields?.length > 0 ? (
                      <div className="space-y-3">
                        <div className="grid grid-cols-3 gap-2 text-center text-xs font-mono">
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

                        {/* Fallback Comparison Cards: OCR Value, Vision Value, Source, Confidence, Status */}
                        <div className="space-y-2">
                          {visionResult.fallback_fields.map((fb, idx) => (
                            <div
                              key={idx}
                              className="rounded-lg bg-background/70 p-3 border border-border/50 text-xs space-y-2"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-semibold text-slate-200">
                                  {formatFieldName(fb.field_name)}
                                </span>
                                <Badge variant="outline" className="text-[9px] uppercase font-bold px-1.5 py-0.2 border-indigo-500/40 text-indigo-300">
                                  {fb.action_taken}
                                </Badge>
                              </div>

                              <div className="grid grid-cols-2 gap-2 text-[10px] font-mono">
                                <div className="rounded bg-background/60 p-2 border border-border/30">
                                  <div className="text-[9px] text-muted-foreground uppercase flex justify-between">
                                    <span>OCR Value</span>
                                    {fb.ocr_confidence != null && <span>{Math.round(fb.ocr_confidence * 100)}%</span>}
                                  </div>
                                  <div className="text-slate-300 break-all font-medium mt-0.5">
                                    {fb.ocr_value != null ? String(fb.ocr_value) : <span className="italic text-muted-foreground">null</span>}
                                  </div>
                                </div>

                                <div className="rounded bg-background/60 p-2 border border-border/30">
                                  <div className="text-[9px] text-indigo-400 uppercase flex justify-between">
                                    <span>Vision Value</span>
                                    {fb.vision_confidence != null && <span>{Math.round(fb.vision_confidence * 100)}%</span>}
                                  </div>
                                  <div className="text-indigo-200 break-all font-medium mt-0.5">
                                    {fb.vision_value != null ? String(fb.vision_value) : <span className="italic text-muted-foreground">null</span>}
                                  </div>
                                </div>
                              </div>

                              {fb.reason && (
                                <div className="text-[10px] text-slate-400 italic bg-muted/20 p-1.5 rounded">
                                  Reason: {fb.reason}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <div className="rounded-lg bg-card/40 border border-border/40 p-4 text-center text-xs text-muted-foreground space-y-1">
                        <CheckCircle2 className="h-4 w-4 text-emerald-400 mx-auto mb-1" />
                        <div className="text-slate-200 font-medium">Vision fallback not required</div>
                        <div className="text-[11px]">All extracted fields satisfied confidence thresholds without visual recovery.</div>
                      </div>
                    )
                  ) : (
                    <div className="rounded-lg bg-card/40 border border-border/40 p-4 text-center text-xs text-muted-foreground">
                      Vision fallback not required
                    </div>
                  )}
                </div>

                {/* RAW OCR INSPECTION ACCORDION */}
                {ocrResult && (
                  <div className="rounded-xl border border-border/60 bg-background/50 overflow-hidden">
                    <button
                      type="button"
                      onClick={() => setShowRawOcr(!showRawOcr)}
                      className="w-full flex items-center justify-between p-3.5 text-xs font-semibold text-slate-300 hover:bg-white/5 transition-colors cursor-pointer text-left"
                    >
                      <div className="flex items-center gap-2">
                        <ScanText className="h-4 w-4 text-blue-400" />
                        <span>Raw OCR Text</span>
                        <span className="text-[11px] font-mono text-muted-foreground">
                          ({ocrResult.page_count} {ocrResult.page_count === 1 ? 'page' : 'pages'} • {ocrResult.metadata?.block_count ?? 0} blocks)
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                        <span>{showRawOcr ? 'Hide' : 'Inspect Text'}</span>
                        {showRawOcr ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                      </div>
                    </button>

                    {showRawOcr && (
                      <div className="p-3.5 pt-0 space-y-3 border-t border-border/40">
                        <div className="flex items-center justify-end gap-1 pt-2">
                          <button
                            type="button"
                            onClick={() => setViewMode('full')}
                            className={`px-2 py-0.5 rounded text-[10px] cursor-pointer ${viewMode === 'full' ? 'bg-primary text-white font-medium' : 'text-muted-foreground hover:text-white'}`}
                          >
                            Full Text
                          </button>
                          <button
                            type="button"
                            onClick={() => setViewMode('blocks')}
                            className={`px-2 py-0.5 rounded text-[10px] cursor-pointer ${viewMode === 'blocks' ? 'bg-primary text-white font-medium' : 'text-muted-foreground hover:text-white'}`}
                          >
                            Blocks ({ocrResult.metadata?.block_count ?? 0})
                          </button>
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
                                  <span className={b.confidence != null && b.confidence >= 80 ? 'text-emerald-400' : 'text-amber-400'}>
                                    {b.confidence != null ? `${b.confidence}%` : 'N/A'}
                                  </span>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* RIGHT COLUMN: SUMMARY & ACTIONS (5 COLS ON DESKTOP) */}
              <div className="lg:col-span-5 space-y-6">
                {/* 5. SUMMARY (Requirement 5: Visually Prominent) */}
                <div className="rounded-xl border border-purple-500/40 bg-purple-950/15 p-4 space-y-4 shadow-lg shadow-purple-950/20">
                  <div className="flex items-center justify-between border-b border-purple-500/20 pb-3">
                    <div className="flex items-center gap-2">
                      <Sparkles className="h-4 w-4 text-purple-400" />
                      <h4 className="text-sm font-bold text-white">Executive Summary</h4>
                    </div>
                    {summaryResult && (
                      <Badge variant="outline" className="text-[10px] font-mono border-purple-500/40 text-purple-300 bg-purple-500/10">
                        {summaryResult.document_type || 'Executive'}
                      </Badge>
                    )}
                  </div>

                  {summaryResult ? (
                    <div className="space-y-3.5">
                      {/* Executive Summary Narrative */}
                      <div className="rounded-lg bg-background/80 p-3 border border-purple-500/20 text-slate-100 text-xs font-sans leading-relaxed">
                        {summaryResult.summary || summaryResult.summary_text || 'No summary text available.'}
                      </div>

                      {/* Key Points (Up to 5) */}
                      {summaryResult.key_points?.length > 0 && (
                        <div className="space-y-1.5">
                          <div className="text-[11px] font-semibold text-slate-200 flex items-center gap-1.5">
                            <CheckSquare className="h-3.5 w-3.5 text-emerald-400" />
                            Key Points ({summaryResult.key_points.length})
                          </div>
                          <div className="space-y-1">
                            {summaryResult.key_points.map((point, idx) => (
                              <div
                                key={idx}
                                className="flex items-start gap-2 rounded bg-background/60 p-2 border border-border/30 text-[11px] text-slate-300 font-sans"
                              >
                                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 mt-1.5 shrink-0" />
                                <span className="flex-1">{point}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Review Items (Up to 5) */}
                      {summaryResult.review_items?.length > 0 && (
                        <div className="space-y-1.5">
                          <div className="text-[11px] font-semibold text-amber-300 flex items-center gap-1.5">
                            <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                            Attention Required ({summaryResult.review_items.length})
                          </div>
                          <div className="space-y-1">
                            {summaryResult.review_items.map((item, idx) => (
                              <div
                                key={idx}
                                className="flex items-start gap-2 rounded bg-amber-950/20 p-2 border border-amber-500/30 text-[11px] text-amber-200 font-sans"
                              >
                                <span className="h-1.5 w-1.5 rounded-full bg-amber-400 mt-1.5 shrink-0" />
                                <span className="flex-1">{item}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="rounded-lg bg-card/40 border border-border/40 p-6 text-center text-xs text-muted-foreground space-y-1">
                      <Sparkles className="h-6 w-6 text-muted-foreground mx-auto mb-1 opacity-40" />
                      <div>Executive summary pending.</div>
                      <div className="text-[11px]">Click &quot;Summary &amp; Actions&quot; or run &quot;Process Document&quot;.</div>
                    </div>
                  )}
                </div>

                {/* 6. ACTIONS (Requirement 6) */}
                <div className="rounded-xl border border-cyan-500/40 bg-cyan-950/15 p-4 space-y-4 shadow-lg shadow-cyan-950/20">
                  <div className="flex items-center justify-between border-b border-cyan-500/20 pb-3">
                    <div className="flex items-center gap-2">
                      <ListTodo className="h-4 w-4 text-cyan-400" />
                      <h4 className="text-sm font-bold text-white">Action Items</h4>
                    </div>
                    {actionsResult && (
                      <Badge variant="outline" className="text-[10px] font-mono border-cyan-500/40 text-cyan-300 bg-cyan-500/10">
                        {actionsResult.actions?.filter((a) => a.status === 'completed').length ?? 0} / {actionsResult.total_actions ?? 0} Done
                      </Badge>
                    )}
                  </div>

                  {actionsResult ? (
                    <div className="space-y-3">
                      {/* Metric Counters */}
                      <div className="grid grid-cols-4 gap-1.5 text-center font-mono text-[10px]">
                        <div className="rounded bg-background/60 p-2 border border-border/40">
                          <div className="text-muted-foreground uppercase text-[9px]">Total</div>
                          <div className="text-xs font-bold text-white mt-0.5">{actionsResult.total_actions ?? 0}</div>
                        </div>
                        <div className="rounded bg-background/60 p-2 border border-rose-500/30">
                          <div className="text-rose-400 uppercase text-[9px]">High</div>
                          <div className="text-xs font-bold text-rose-400 mt-0.5">{actionsResult.high_priority_count ?? 0}</div>
                        </div>
                        <div className="rounded bg-background/60 p-2 border border-amber-500/30">
                          <div className="text-amber-400 uppercase text-[9px]">Pending</div>
                          <div className="text-xs font-bold text-amber-400 mt-0.5">
                            {actionsResult.actions?.filter((a) => a.status === 'pending').length ?? 0}
                          </div>
                        </div>
                        <div className="rounded bg-background/60 p-2 border border-emerald-500/30">
                          <div className="text-emerald-400 uppercase text-[9px]">Done</div>
                          <div className="text-xs font-bold text-emerald-400 mt-0.5">
                            {actionsResult.actions?.filter((a) => a.status === 'completed').length ?? 0}
                          </div>
                        </div>
                      </div>

                      {/* Action Items List */}
                      {actionsResult.actions?.length > 0 ? (
                        <div className="space-y-2.5 max-h-[480px] overflow-y-auto pr-1">
                          {actionsResult.actions.map((act) => {
                            const isHigh = act.priority === 'high';
                            const isMed = act.priority === 'medium';
                            const isCompleted = act.status === 'completed';
                            const isInProgress = act.status === 'in_progress';
                            const isUpdating = actionUpdatingId === act.id;
                            const actionTitle = act.action || act.title || 'Untitled Action';

                            return (
                              <div
                                key={act.id}
                                className={`rounded-lg p-3 border text-xs space-y-2 transition-all ${
                                  isCompleted
                                    ? 'border-emerald-500/30 bg-emerald-950/10 opacity-75'
                                    : isInProgress
                                      ? 'border-blue-500/40 bg-blue-950/20'
                                      : isHigh
                                        ? 'border-rose-500/40 bg-rose-950/15'
                                        : 'border-border/40 bg-background/70'
                                }`}
                              >
                                <div className="flex items-start justify-between gap-2">
                                  {/* Action & Priority */}
                                  <div className="flex items-start gap-2 flex-1 min-w-0">
                                    <Badge
                                      variant="outline"
                                      className={`text-[9px] uppercase font-bold shrink-0 px-1.5 py-0.2 ${
                                        isHigh
                                          ? 'border-rose-500/50 bg-rose-500/10 text-rose-300'
                                          : isMed
                                            ? 'border-amber-500/50 bg-amber-500/10 text-amber-300'
                                            : 'border-slate-500/50 bg-slate-500/10 text-slate-300'
                                      }`}
                                    >
                                      {act.priority}
                                    </Badge>
                                    <span className={`font-medium text-xs text-white font-sans ${isCompleted ? 'line-through text-slate-400' : ''}`}>
                                      {actionTitle}
                                    </span>
                                  </div>

                                  {/* Status Selector Dropdown */}
                                  <div className="shrink-0">
                                    {isUpdating ? (
                                      <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                                    ) : (
                                      <select
                                        value={act.status}
                                        onChange={(e) => handleUpdateActionStatus(act.id, e.target.value)}
                                        className={`text-[10px] font-mono px-2 py-1 rounded border cursor-pointer bg-background transition-colors ${
                                          isCompleted
                                            ? 'border-emerald-500/50 text-emerald-300'
                                            : isInProgress
                                              ? 'border-blue-500/50 text-blue-300'
                                              : 'border-amber-500/50 text-amber-300'
                                        }`}
                                      >
                                        <option value="pending">Pending</option>
                                        <option value="in_progress">In Progress</option>
                                        <option value="completed">Completed</option>
                                        <option value="dismissed">Dismissed</option>
                                      </select>
                                    )}
                                  </div>
                                </div>

                                {/* Due Date & Source */}
                                <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-muted-foreground pt-1 border-t border-border/20">
                                  <div className="flex items-center gap-1.5">
                                    <Calendar className="h-3 w-3 text-slate-400" />
                                    <span>
                                      {act.due_date ? (
                                        <span className="text-amber-300 font-semibold font-mono">Due: {act.due_date}</span>
                                      ) : (
                                        <span className="italic text-slate-500">No due date</span>
                                      )}
                                    </span>
                                  </div>
                                  <div className="flex items-center gap-1.5">
                                    <span className="text-slate-500">Source:</span>
                                    <span className="text-slate-300 capitalize">{act.source?.replace('_', ' ') || 'rule based'}</span>
                                  </div>
                                </div>

                                {/* Grounding Reason Footnote */}
                                {act.reason && (
                                  <div className="text-[10px] text-slate-400 italic bg-background/50 p-1.5 rounded border border-border/20">
                                    Reason: {act.reason}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <div className="text-xs text-muted-foreground italic text-center py-4">
                          No actionable tasks extracted for this document.
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="rounded-lg bg-card/40 border border-border/40 p-6 text-center text-xs text-muted-foreground space-y-1">
                      <ListTodo className="h-6 w-6 text-muted-foreground mx-auto mb-1 opacity-40" />
                      <div>Action items pending.</div>
                      <div className="text-[11px]">Click &quot;Summary &amp; Actions&quot; or run &quot;Process Document&quot;.</div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* ============================================================ */
          /* STATE 2: DOCUMENT DROPZONE & FILE SELECTION                  */
          /* ============================================================ */
          <div className="space-y-4">
            <div
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={() => inputRef.current?.click()}
              className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center cursor-pointer transition-all duration-200 ${
                dragActive
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
                  Drag &amp; drop your document here
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

            {/* Selected File Inspection Card */}
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
