import { usePageTitle } from "@/hooks/use-page-title";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Palette,
  ExternalLink,
  GitBranch,
  ArrowRight,
  CheckCircle,
  Monitor,
} from "lucide-react";

export default function StitchAccessPage() {
  usePageTitle("Design Lab — Stitch");

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Design Lab</h1>
          <p className="text-muted-foreground mt-1">
            Visual UI design with Google Stitch, orchestrated through IWO2 workflows
          </p>
        </div>
        <Badge variant="secondary" className="text-xs">External Tool</Badge>
      </div>

      {/* Launch Card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Palette className="w-5 h-5" />
            Open Stitch
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Stitch is Google's AI-powered visual design tool for creating UI layouts,
            components, and full-page designs from prompts or reference images.
            It runs externally — IWO2 manages the workflow around it.
          </p>
          <Button
            onClick={() => window.open("https://stitch.withgoogle.com", "_blank", "noopener")}
            className="gap-2"
          >
            <ExternalLink className="w-4 h-4" />
            Open Stitch
          </Button>
        </CardContent>
      </Card>

      {/* How It Works */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <GitBranch className="w-5 h-5" />
            Workflow-First Model
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground mb-4">
            Stitch design work flows through a dedicated IWO2 workflow — not a one-step
            work order. The workflow ensures design review happens before build, and
            preview review happens before publish.
          </p>
          <div className="space-y-3">
            {[
              { step: "1", label: "Submit a design request", desc: "Create a work order via Chat or Submit Order. Aiden routes it to the Stitch workflow." },
              { step: "2", label: "Design brief prepared", desc: "Mark produces a Stitch prompt packet with goals, constraints, and brand references." },
              { step: "3", label: "Design in Stitch", desc: "Open Stitch, create your design, then paste the project URL back into IWO2." },
              { step: "4", label: "Sync and attach", desc: "Upload screenshots or a DESIGN.md. Record which variant you selected." },
              { step: "5", label: "Design review gate", desc: "Approve the design direction before any code is written. Return to Stitch if needed." },
              { step: "6", label: "Frontend build", desc: "Hank converts the approved design into an implementation scaffold." },
              { step: "7", label: "Preview review gate", desc: "Review the build output. Request revisions or approve for publish." },
              { step: "8", label: "Publish or file", desc: "Paul handles final deployment or artifact filing." },
            ].map((item) => (
              <div key={item.step} className="flex gap-3 items-start">
                <div className="flex items-center justify-center w-6 h-6 rounded-full bg-primary text-primary-foreground text-xs font-bold shrink-0 mt-0.5">
                  {item.step}
                </div>
                <div>
                  <p className="text-sm font-medium">{item.label}</p>
                  <p className="text-xs text-muted-foreground">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Operator Setup */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Monitor className="w-5 h-5" />
            Operator Setup
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-start gap-2">
            <CheckCircle className="w-4 h-4 text-green-500 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium">Access Stitch</p>
              <p className="text-xs text-muted-foreground">
                Sign in at{" "}
                <a
                  href="https://stitch.withgoogle.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline"
                >
                  stitch.withgoogle.com
                </a>{" "}
                with your Google account.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-2">
            <CheckCircle className="w-4 h-4 text-green-500 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium">Use the Stitch workflow</p>
              <p className="text-xs text-muted-foreground">
                Ask Aiden to create a design request, or submit a work order with a visual
                design goal. Aiden will route it to the "Stitch Design to Frontend Workflow."
              </p>
            </div>
          </div>
          <div className="flex items-start gap-2">
            <CheckCircle className="w-4 h-4 text-green-500 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium">Paste your project URL</p>
              <p className="text-xs text-muted-foreground">
                After designing in Stitch, paste the project URL into the Stitch panel on
                your work order detail page. Upload screenshots or a DESIGN.md to capture
                the design output.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-2">
            <ArrowRight className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium">Review and approve</p>
              <p className="text-xs text-muted-foreground">
                Two explicit review gates ensure you approve the design before build and
                the build before publish. Nothing ships without your approval.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
