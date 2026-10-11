"use client";

import { FileText, MoreHorizontal, Search, Settings, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FadeIn, Presence } from "@/components/motion/presets";
import { Badge } from "@/components/primitives/badge";
import { Button, IconButton } from "@/components/primitives/button";
import { Checkbox } from "@/components/primitives/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/primitives/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/primitives/dropdown-menu";
import { Input } from "@/components/primitives/input";
import { Kbd } from "@/components/primitives/kbd";
import { Label } from "@/components/primitives/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/primitives/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/primitives/select";
import { Separator } from "@/components/primitives/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/primitives/sheet";
import { Skeleton } from "@/components/primitives/skeleton";
import { StatusBadge } from "@/components/primitives/status-badge";
import { Switch } from "@/components/primitives/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/primitives/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/primitives/tabs";
import { Textarea } from "@/components/primitives/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/primitives/tooltip";
import { ThemeToggle } from "@/components/theme-toggle";

function Section({
  title,
  align = "center",
  children,
}: {
  title: string;
  align?: "center" | "start";
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={`section-${title}`} className="flex flex-col gap-3">
      <h2
        id={`section-${title}`}
        className="text-xs font-semibold tracking-wide text-ink-tertiary uppercase"
      >
        {title}
      </h2>
      <div className={`flex flex-wrap gap-3 ${align === "start" ? "items-start" : "items-center"}`}>
        {children}
      </div>
    </section>
  );
}

const documents = [
  {
    title: "Employee Handbook 2026",
    type: "PDF",
    version: "v3",
    status: "success",
    label: "Ready",
  },
  {
    title: "Support Runbook",
    type: "Markdown",
    version: "v7",
    status: "progress",
    label: "Embedding",
  },
  { title: "Vendor Contract", type: "DOCX", version: "v1", status: "danger", label: "Failed" },
] as const;

export function PrimitivesShowcase() {
  const [compact, setCompact] = useState(false);
  const [showNotice, setShowNotice] = useState(true);

  return (
    <div data-density={compact ? "compact" : "comfortable"} className="flex flex-col gap-10">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-6">
        <div className="flex flex-col gap-1">
          <p className="font-mono text-xs text-ink-tertiary">/dev/primitives · development only</p>
          <h1 className="text-xl font-semibold tracking-tight">KnowledgeOS primitives</h1>
          <p className="max-w-prose text-ink-secondary">
            The &ldquo;Knowledge Instrument&rdquo; design foundation: tokens, typography, motion and
            restyled accessible primitives.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Switch id="density" checked={compact} onCheckedChange={setCompact} />
            <Label htmlFor="density">Compact density</Label>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <Section title="Typography">
        <div className="flex w-full flex-col gap-3">
          <p className="text-2xl font-semibold tracking-tight">Ask your organization</p>
          <p className="text-base">
            UI text is Instrument Sans at 14px.{" "}
            <span className="text-ink-secondary">Secondary ink.</span>{" "}
            <span className="text-ink-tertiary">Tertiary ink for metadata.</span>
          </p>
          <p className="prose-reading">
            Long-form answers use Source Serif 4 at a comfortable reading measure. Parental leave is
            sixteen weeks for primary caregivers, effective January 2026{" "}
            <a className="text-accent underline underline-offset-4" href="#typography">
              [S1]
            </a>
            .
          </p>
          <p className="font-mono text-sm text-ink-secondary">
            chunk_id 0192a8f4-77c1 · rerank 0.8731 · <span className="tabular">1,204 ms</span>
          </p>
        </div>
      </Section>

      <Section title="Buttons">
        <Button variant="primary">Ask</Button>
        <Button>Secondary</Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="danger">
          <Trash2 aria-hidden="true" /> Delete
        </Button>
        <Button variant="link">Open document</Button>
        <Button size="sm">Small</Button>
        <Button size="lg" variant="primary">
          <Search aria-hidden="true" /> Large
        </Button>
        <Button disabled>Disabled</Button>
        <IconButton aria-label="Settings">
          <Settings aria-hidden="true" />
        </IconButton>
      </Section>

      <Section title="Form controls" align="start">
        <div className="flex w-72 flex-col gap-1.5">
          <Label htmlFor="kb-name">Library name</Label>
          <Input id="kb-name" placeholder="e.g. HR policies" />
        </div>
        <div className="flex w-72 flex-col gap-1.5">
          <Label htmlFor="kb-invalid">Slug</Label>
          <Input
            id="kb-invalid"
            defaultValue="HR Policies!"
            aria-invalid="true"
            aria-describedby="kb-invalid-hint"
          />
          <p id="kb-invalid-hint" className="text-xs text-danger">
            Use lowercase letters, numbers and dashes.
          </p>
        </div>
        <div className="flex w-56 flex-col gap-1.5">
          <Label htmlFor="classification">Classification</Label>
          <Select defaultValue="internal">
            <SelectTrigger id="classification" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="public">Public</SelectItem>
              <SelectItem value="internal">Internal</SelectItem>
              <SelectItem value="confidential">Confidential</SelectItem>
              <SelectItem value="restricted">Restricted</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex w-full max-w-xl flex-col gap-1.5">
          <Label htmlFor="question">Question</Label>
          <Textarea
            id="question"
            placeholder="Ask a question, compare policies, find a document…"
          />
        </div>
        <div className="flex items-center gap-2">
          <Checkbox id="only-verified" defaultChecked />
          <Label htmlFor="only-verified">Only verified sources</Label>
        </div>
      </Section>

      <Section title="Status">
        <StatusBadge status="success">Ready</StatusBadge>
        <StatusBadge status="progress">Embedding</StatusBadge>
        <StatusBadge status="warning">Partial evidence</StatusBadge>
        <StatusBadge status="danger">Failed</StatusBadge>
        <StatusBadge status="info">Verified</StatusBadge>
        <StatusBadge status="neutral">Queued</StatusBadge>
        <Badge variant="secondary">policy</Badge>
        <Badge variant="outline">HR</Badge>
        <span className="inline-flex items-center gap-1 text-sm text-ink-secondary">
          Command palette <Kbd>Ctrl</Kbd>
          <Kbd>K</Kbd>
        </span>
      </Section>

      <Section title="Tabs">
        <Tabs defaultValue="answer" className="w-full max-w-xl">
          <TabsList aria-label="Result view">
            <TabsTrigger value="answer">Answer</TabsTrigger>
            <TabsTrigger value="sources">Sources</TabsTrigger>
            <TabsTrigger value="trace">Trace</TabsTrigger>
          </TabsList>
          <TabsContent value="answer" className="text-ink-secondary">
            Document-like generated content with inline citations.
          </TabsContent>
          <TabsContent value="sources" className="text-ink-secondary">
            7 sources searched.
          </TabsContent>
          <TabsContent value="trace" className="text-ink-secondary">
            Retrieval 312 ms · rerank 640 ms.
          </TabsContent>
        </Tabs>
        <Tabs defaultValue="documents" className="w-full max-w-xl">
          <TabsList variant="line" aria-label="Knowledge section">
            <TabsTrigger value="documents">Documents</TabsTrigger>
            <TabsTrigger value="sources">Sources</TabsTrigger>
            <TabsTrigger value="permissions">Permissions</TabsTrigger>
          </TabsList>
          <TabsContent value="documents" className="text-ink-secondary">
            1,204 documents across 4 libraries.
          </TabsContent>
          <TabsContent value="sources" className="text-ink-secondary">
            Upload, website and Google Drive sources.
          </TabsContent>
          <TabsContent value="permissions" className="text-ink-secondary">
            Restricted to the HR group.
          </TabsContent>
        </Tabs>
      </Section>

      <Section title="Overlays">
        <Dialog>
          <DialogTrigger asChild>
            <Button>Open dialog</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Archive document?</DialogTitle>
              <DialogDescription>
                It stops appearing in search and answers immediately. Version history is kept.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="danger">Archive</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <Sheet>
          <SheetTrigger asChild>
            <Button>Open evidence sheet</Button>
          </SheetTrigger>
          <SheetContent>
            <SheetHeader>
              <SheetTitle>Employee Handbook 2026</SheetTitle>
              <SheetDescription>Page 14 · §4.2 Parental leave</SheetDescription>
            </SheetHeader>
          </SheetContent>
        </Sheet>
        <Popover>
          <PopoverTrigger asChild>
            <Button>Popover</Button>
          </PopoverTrigger>
          <PopoverContent className="text-sm">Filters live here.</PopoverContent>
        </Popover>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <IconButton aria-label="Document actions" variant="secondary">
              <MoreHorizontal aria-hidden="true" />
            </IconButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuItem>
              <FileText aria-hidden="true" /> Open
            </DropdownMenuItem>
            <DropdownMenuItem>Reindex</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive">Delete</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button>Tooltip</Button>
          </TooltipTrigger>
          <TooltipContent>Restricted to HR group</TooltipContent>
        </Tooltip>
        <Button
          onClick={() => toast("Document archived", { description: "Employee Handbook 2025" })}
        >
          Toast
        </Button>
      </Section>

      <Section title="Table">
        <div className="w-full overflow-x-auto rounded-panel border border-line bg-surface-1">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {documents.map((doc) => (
                <TableRow key={doc.title} className="h-(--row-height)">
                  <TableCell className="font-medium">{doc.title}</TableCell>
                  <TableCell className="text-ink-secondary">{doc.type}</TableCell>
                  <TableCell className="font-mono text-ink-secondary">{doc.version}</TableCell>
                  <TableCell>
                    <StatusBadge status={doc.status}>{doc.label}</StatusBadge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </Section>

      <Section title="Loading & motion">
        <div className="flex w-full max-w-xl flex-col gap-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
        <Separator className="my-1" />
        <Button onClick={() => setShowNotice((v) => !v)}>
          {showNotice ? "Dismiss notice" : "Show notice"}
        </Button>
        <Presence>
          {showNotice && (
            <FadeIn
              key="notice"
              className="rounded-control border border-line bg-warning-soft px-3 py-2 text-sm text-warning"
            >
              Reranking unavailable; using fused retrieval ordering.
            </FadeIn>
          )}
        </Presence>
      </Section>
    </div>
  );
}
