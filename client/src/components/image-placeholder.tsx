import { useState, useRef, useCallback } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { queryClient, apiRequest } from "@/lib/queryClient";
import { useToast } from "@/hooks/use-toast";
import { ImageIcon, Upload, X, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ImagePlaceholderProps {
  placeholderId: string;
  label?: string;
  aspectRatio?: string;
  className?: string;
  width?: string | number;
  height?: string | number;
  editable?: boolean;
}

export function ImagePlaceholder({
  placeholderId,
  label,
  aspectRatio = "16/9",
  className = "",
  width,
  height,
  editable = true,
}: ImagePlaceholderProps) {
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const { data: imageMeta, isLoading } = useQuery<{ exists: boolean; filename?: string; mimeType?: string; size?: number; alt?: string }>({
    queryKey: ["/api/images", placeholderId, "meta"],
    queryFn: async () => {
      const res = await fetch(`/api/images/${placeholderId}/meta`);
      if (!res.ok) return { exists: false };
      return res.json();
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const reader = new FileReader();
      const dataUrl = await new Promise<string>((resolve, reject) => {
        reader.onload = () => resolve(reader.result as string);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      return apiRequest("POST", "/api/images/upload", {
        placeholderId,
        filename: file.name,
        mimeType: file.type,
        data: dataUrl,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/images", placeholderId, "meta"] });
      toast({ title: "Image uploaded", description: "The placeholder has been filled." });
    },
    onError: () => {
      toast({ title: "Upload failed", description: "Could not upload image. Check file size (max 5MB).", variant: "destructive" });
    },
  });

  const removeMutation = useMutation({
    mutationFn: () => apiRequest("DELETE", `/api/images/${placeholderId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/images", placeholderId, "meta"] });
      toast({ title: "Image removed" });
    },
  });

  const handleFile = useCallback(
    (file: File) => {
      const allowed = ["image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"];
      if (!allowed.includes(file.type)) {
        toast({ title: "Invalid file type", description: "Please upload a PNG, JPEG, GIF, WebP, or SVG.", variant: "destructive" });
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        toast({ title: "File too large", description: "Maximum file size is 5MB.", variant: "destructive" });
        return;
      }
      uploadMutation.mutate(file);
    },
    [uploadMutation, toast]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
  }, []);

  const handleClick = () => {
    if (editable && fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const hasImage = imageMeta?.exists;
  const imageUrl = `/api/images/${placeholderId}?t=${Date.now()}`;

  const sizeStyle: React.CSSProperties = {};
  if (width) sizeStyle.width = typeof width === "number" ? `${width}px` : width;
  if (height) sizeStyle.height = typeof height === "number" ? `${height}px` : height;
  if (!width && !height) sizeStyle.aspectRatio = aspectRatio;

  if (isLoading) {
    return (
      <div
        className={`relative rounded-lg border-2 border-dashed border-muted-foreground/20 bg-muted/30 flex items-center justify-center ${className}`}
        style={sizeStyle}
        data-testid={`image-placeholder-${placeholderId}`}
      >
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (hasImage) {
    return (
      <div
        className={`relative group rounded-lg overflow-hidden ${className}`}
        style={sizeStyle}
        data-testid={`image-placeholder-${placeholderId}`}
      >
        <img
          src={imageUrl}
          alt={imageMeta?.alt || label || "Uploaded image"}
          className="w-full h-full object-cover"
          data-testid={`image-display-${placeholderId}`}
        />
        {editable && (
          <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={(e) => {
                e.stopPropagation();
                handleClick();
              }}
              data-testid={`button-replace-image-${placeholderId}`}
            >
              <Upload className="w-3.5 h-3.5 mr-1" />
              Replace
            </Button>
            <Button
              size="sm"
              variant="destructive"
              onClick={(e) => {
                e.stopPropagation();
                removeMutation.mutate();
              }}
              data-testid={`button-remove-image-${placeholderId}`}
            >
              <X className="w-3.5 h-3.5 mr-1" />
              Remove
            </Button>
          </div>
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
          className="hidden"
          onChange={handleInputChange}
        />
      </div>
    );
  }

  return (
    <div
      className={`relative rounded-lg border-2 border-dashed transition-colors cursor-pointer ${
        isDragOver
          ? "border-primary bg-primary/5"
          : "border-muted-foreground/25 bg-muted/20 hover:border-muted-foreground/40 hover:bg-muted/30"
      } ${className}`}
      style={sizeStyle}
      onDrop={editable ? handleDrop : undefined}
      onDragOver={editable ? handleDragOver : undefined}
      onDragLeave={editable ? handleDragLeave : undefined}
      onClick={editable ? handleClick : undefined}
      data-testid={`image-placeholder-${placeholderId}`}
    >
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4">
        {uploadMutation.isPending ? (
          <>
            <Loader2 className="w-8 h-8 animate-spin text-primary" />
            <span className="text-xs text-muted-foreground">Uploading...</span>
          </>
        ) : (
          <>
            <ImageIcon className="w-8 h-8 text-muted-foreground/50" />
            {label && (
              <span className="text-xs font-medium text-muted-foreground text-center">{label}</span>
            )}
            {editable && (
              <span className="text-[10px] text-muted-foreground/70 text-center">
                {isDragOver ? "Drop image here" : "Click or drag & drop to upload"}
              </span>
            )}
          </>
        )}
      </div>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
        className="hidden"
        onChange={handleInputChange}
      />
    </div>
  );
}
