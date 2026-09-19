import React, { useState, useEffect, useCallback } from 'react';
import { api } from '@/services/api';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { 
  Activity, 
  CheckCircle2, 
  XCircle, 
  RefreshCw, 
  Server, 
  Layers, 
  ArrowRight,
  ShieldCheck,
  Terminal,
  Zap
} from 'lucide-react';

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
      <header className="relative z-10 mx-auto w-full max-w-5xl flex items-center justify-between pb-6 border-b border-border/40">
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
      <main className="relative z-10 mx-auto my-auto w-full max-w-3xl py-12 text-center">
        {/* Foundation Tag */}
        <div className="inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3.5 py-1 text-xs font-medium text-primary mb-6 backdrop-blur-md">
          <Zap className="h-3.5 w-3.5" />
          Phase 1 — Project Foundation & Development Environment
        </div>

        {/* Hero Title */}
        <h2 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-white mb-4">
          Document-to-Action <br />
          <span className="bg-gradient-to-r from-blue-400 via-indigo-300 to-purple-400 bg-clip-text text-transparent">
            Pipeline
          </span>
        </h2>

        {/* Required Short Description */}
        <p className="mx-auto max-w-2xl text-lg sm:text-xl text-slate-300 font-normal leading-relaxed mb-10">
          Transform messy documents into structured, validated and actionable information.
        </p>

        {/* Live System Connectivity Card */}
        <Card className="mx-auto max-w-xl border-border/60 bg-card/60 backdrop-blur-xl shadow-2xl text-left">
          <CardHeader className="pb-3 border-b border-border/40">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <Server className="h-4 w-4 text-primary" />
                <CardTitle className="text-base text-white">System Connectivity & Health</CardTitle>
              </div>
              <Badge variant="outline" className="text-xs font-mono text-muted-foreground border-border/50">
                GET /health
              </Badge>
            </div>
            <CardDescription className="text-xs text-muted-foreground">
              Verifying frontend ↔ FastAPI backend API connection
            </CardDescription>
          </CardHeader>

          <CardContent className="pt-5 space-y-4">
            {/* Status indicator row */}
            <div className="flex items-center justify-between rounded-lg border border-border/50 bg-background/50 p-3.5">
              <div className="flex items-center gap-3">
                {healthState.loading ? (
                  <RefreshCw className="h-5 w-5 text-muted-foreground animate-spin" />
                ) : isConnected ? (
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-400">
                    <CheckCircle2 className="h-5 w-5" />
                  </div>
                ) : (
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-rose-500/20 text-rose-400">
                    <XCircle className="h-5 w-5" />
                  </div>
                )}
                <div>
                  <div className="text-sm font-semibold text-white flex items-center gap-2">
                    Backend Status:{" "}
                    <span className={isConnected ? "text-emerald-400" : "text-rose-400"}>
                      {healthState.status}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Endpoint: <code className="text-slate-300 font-mono">{api.getBaseUrl()}/health</code>
                  </div>
                </div>
              </div>

              {healthState.latencyMs !== null && (
                <div className="text-right">
                  <span className="text-xs font-mono text-muted-foreground block">Latency</span>
                  <span className="text-xs font-mono font-semibold text-emerald-400">
                    {healthState.latencyMs} ms
                  </span>
                </div>
              )}
            </div>

            {/* Health payload output */}
            {isConnected && healthState.rawData && (
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-950/10 p-3 text-xs font-mono text-slate-300">
                <div className="text-muted-foreground text-[10px] uppercase tracking-wider mb-1 flex items-center gap-1">
                  <Terminal className="h-3 w-3" /> Response Payload
                </div>
                <pre className="text-emerald-300">{JSON.stringify(healthState.rawData, null, 2)}</pre>
              </div>
            )}

            {/* Error output if disconnected */}
            {!isConnected && healthState.error && (
              <div className="rounded-lg border border-rose-500/20 bg-rose-950/10 p-3 text-xs font-mono text-rose-300">
                <div className="text-muted-foreground text-[10px] uppercase tracking-wider mb-1">
                  Connection Error
                </div>
                <div>{healthState.error}</div>
              </div>
            )}

            {/* Action buttons and info */}
            <div className="flex items-center justify-between pt-2">
              <div className="text-xs text-muted-foreground">
                {healthState.lastChecked && `Last checked: ${healthState.lastChecked}`}
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={checkStatus}
                disabled={healthState.loading}
                className="gap-1.5 text-xs"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${healthState.loading ? "animate-spin" : ""}`} />
                Ping Health
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Readiness Checklist */}
        <div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-3 text-left max-w-xl mx-auto">
          <div className="p-3 rounded-lg border border-border/40 bg-card/40 backdrop-blur-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-emerald-400 mb-1">
              <ShieldCheck className="h-3.5 w-3.5" /> Frontend Ready
            </div>
            <p className="text-[11px] text-muted-foreground">React + Vite + Tailwind + shadcn/ui configured</p>
          </div>
          <div className="p-3 rounded-lg border border-border/40 bg-card/40 backdrop-blur-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-emerald-400 mb-1">
              <ShieldCheck className="h-3.5 w-3.5" /> Backend Ready
            </div>
            <p className="text-[11px] text-muted-foreground">FastAPI + CORS + Health endpoint verified</p>
          </div>
          <div className="p-3 rounded-lg border border-border/40 bg-card/40 backdrop-blur-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-blue-400 mb-1">
              <ArrowRight className="h-3.5 w-3.5" /> Next: Phase 2
            </div>
            <p className="text-[11px] text-muted-foreground">Ready for Supabase DB & Gemini integration</p>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 mx-auto w-full max-w-5xl pt-6 border-t border-border/40 text-center text-xs text-muted-foreground">
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
