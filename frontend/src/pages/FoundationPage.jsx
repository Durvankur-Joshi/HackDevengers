import React, { useState, useEffect, useCallback } from 'react';
import { api } from '@/services/api';
import DocumentUpload from '@/components/DocumentUpload';
import { Badge } from '@/components/ui/badge';
import { Layers, Zap } from 'lucide-react';

export default function FoundationPage() {
  const [healthState, setHealthState] = useState({
    loading: true,
    status: 'Checking...',
    connected: false,
    latencyMs: null,
    error: null,
    lastChecked: null,
    rawData: null,
  });

  const checkStatus = useCallback(async () => {
    setHealthState((prev) => ({ ...prev, loading: true }));
    const result = await api.checkHealth();
    setHealthState({
      loading: false,
      status: result.status,
      connected: result.ok,
      latencyMs: result.latencyMs,
      error: result.error || null,
      lastChecked: new Date().toLocaleTimeString(),
      rawData: result.raw || null,
    });
  }, []);

  useEffect(() => {
    checkStatus();
    // Periodically verify every 10 seconds
    const interval = setInterval(checkStatus, 10000);
    return () => clearInterval(interval);
  }, [checkStatus]);

  const isConnected = healthState.connected;

  return (
    <div className="relative min-h-screen flex flex-col justify-between overflow-hidden px-4 py-8 sm:px-6 lg:px-8">
      {/* Background glowing orbs */}
      <div className="pointer-events-none absolute -top-40 -left-40 h-96 w-96 rounded-full bg-blue-600/15 blur-3xl" />
      <div className="pointer-events-none absolute top-1/2 -right-40 h-96 w-96 rounded-full bg-indigo-600/15 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 left-1/3 h-96 w-96 rounded-full bg-violet-600/10 blur-3xl" />

      {/* Top Navigation / Header */}
      <header className="relative z-10 mx-auto w-full max-w-6xl flex items-center justify-between pb-6 border-b border-border/40">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 border border-primary/30 text-primary shadow-[0_0_15px_rgba(59,130,246,0.3)]">
            <Layers className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
              HackDevengers
              <span className="text-xs font-normal text-muted-foreground">/ pipeline</span>
            </h1>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Badge variant={isConnected ? "success" : "danger"} className="gap-1.5 py-1 px-3">
            <span className={`h-2 w-2 rounded-full ${isConnected ? "bg-emerald-400 animate-pulse" : "bg-rose-400"}`} />
            Backend Status: {isConnected ? "Connected" : "Disconnected"}
          </Badge>
        </div>
      </header>

      {/* Main Foundation Showcase */}
      <main className="relative z-10 mx-auto my-auto w-full max-w-6xl py-8 text-center">
        {/* Product Tag */}
        <div className="inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3.5 py-1 text-xs font-medium text-primary mb-5 backdrop-blur-md">
          <Zap className="h-3.5 w-3.5" />
          Automated Document-to-Action Engine
        </div>

        {/* Hero Title */}
        <h2 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight text-white mb-3">
          Document-to-Action <br />
          <span className="bg-gradient-to-r from-blue-400 via-indigo-300 to-purple-400 bg-clip-text text-transparent">
            Pipeline
          </span>
        </h2>

        {/* Required Short Description */}
        <p className="mx-auto max-w-2xl text-base sm:text-lg text-slate-300 font-normal leading-relaxed mb-8">
          Transform messy documents into structured, validated and actionable information.
        </p>

        {/* Document Ingestion & Pipeline Dashboard */}
        <div className="w-full">
          <DocumentUpload />
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 mx-auto w-full max-w-6xl pt-6 border-t border-border/40 text-center text-xs text-muted-foreground">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-2">
          <span>Document-to-Action Pipeline • HackDevengers</span>
          <div className="flex items-center gap-3">
            <span className="hover:text-foreground transition-colors">FastAPI</span>
            <span>•</span>
            <span className="hover:text-foreground transition-colors">React Vite</span>
            <span>•</span>
            <span className="hover:text-foreground transition-colors">Tailwind CSS</span>
            <span>•</span>
            <span className="hover:text-foreground transition-colors">shadcn/ui</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
