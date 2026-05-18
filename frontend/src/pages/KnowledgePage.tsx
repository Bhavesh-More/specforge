import { useState } from "react";
import { Search, Plus } from "lucide-react";
import { useKnowledgeFiles, useMutations } from "../hooks/useSpecForgeAPI";

export function KnowledgePage() {
  const { data: files } = useKnowledgeFiles();

  const {
    updateKnowledgeFile,
    createKnowledgeFile,
  } = useMutations();

  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState<string>("");

  if (!files) {
    return (
      <div className="flex h-full">
        <div className="w-[280px] shrink-0 border-r border-sf-border bg-sf-bg-deep p-4">
          <Skeleton />
        </div>

        <div className="flex-1 flex items-center justify-center">
          <span className="text-sm text-sf-text-muted">
            ← Select a rule file
          </span>
        </div>
      </div>
    );
  }

  // Load content when file is selected
  const selectedFile = files.find((f) => f.name === selected);

  if (selected && selectedFile && content !== selectedFile.content) {
    setContent(selectedFile.content);
  }

  async function handleSave() {
    if (!selected) return;

    try {
      await updateKnowledgeFile.mutateAsync({
        name: selected,
        content,
      });

      alert("File saved!");
    } catch (err) {
      alert("Save failed: " + (err as Error).message);
    }
  }

  async function handleCreateFile() {
    const name = prompt("New file name:");

    if (!name) return;

    try {
      await createKnowledgeFile.mutateAsync({
        name,
        content: "// New rule file",
      });

      alert("File created!");
    } catch (err) {
      alert("Failed to create file: " + (err as Error).message);
    }
  }

  return (
    <div className="flex h-full">
      {/* Left panel */}
      <div className="w-[280px] shrink-0 flex flex-col border-r border-sf-border bg-sf-bg-deep">
        {/* Search bar */}
        <div className="px-3 py-[10px] border-b border-sf-border flex items-center gap-2">
          <div className="flex-1 relative">
            <Search
              size={13}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-sf-text-muted"
            />

            <input
              type="text"
              placeholder="Search files…"
              className="w-full bg-sf-bg border border-sf-border-standard rounded-btn pl-8 pr-3 py-1.5 text-[13px] text-sf-text placeholder-sf-text-muted outline-none focus:border-sf-border-strong"
            />
          </div>

          <button
            className="p-1.5 text-sf-text-muted hover:text-sf-text transition-colors rounded-btn"
            onClick={handleCreateFile}
          >
            <Plus size={14} />
          </button>
        </div>

        {/* File list */}
        <div className="flex-1 overflow-y-auto">
          {files.map((file) => (
            <div
              key={file.name}
              onClick={() => setSelected(file.name)}
              className={`px-3 py-[10px] border-b border-sf-border cursor-pointer transition-colors duration-100 hover:bg-[rgba(255,255,255,0.03)] ${
                selected === file.name
                  ? "text-sf-text border-l-2 border-sf-green bg-[rgba(62,207,142,0.05)]"
                  : "text-sf-text-secondary"
              }`}
            >
              <div className="font-mono text-[13px]">
                {file.name}
              </div>

              <div className="font-mono text-[11px] text-sf-text-muted mt-0.5">
                ↗ {file.linked_files.length} links
              </div>
            </div>
          ))}
        </div>

        {/* Graph stats */}
        <div className="px-3 py-3 border-t border-sf-border">
          <div className="bg-sf-bg border border-sf-border-standard rounded-btn p-3">
            <div className="font-mono text-[10px] uppercase tracking-[1.2px] text-sf-text-muted mb-2">
              Graph Stats
            </div>

            <div className="space-y-1 text-xs">
              <div className="flex justify-between">
                <span className="text-sf-text-muted">Files</span>

                <span className="text-sf-text">
                  {files.length}
                </span>
              </div>

              <div className="flex justify-between">
                <span className="text-sf-text-muted">Links</span>

                <span className="text-sf-text">
                  {files.reduce(
                    (sum, f) => sum + f.linked_files.length,
                    0
                  )}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Right panel */}
      <div className="flex-1 flex flex-col bg-sf-bg">
        {selected ? (
          <>
            <div className="h-[44px] shrink-0 flex items-center justify-between px-4 border-b border-sf-border">
              <span className="font-mono text-[13px] text-sf-text">
                {selected}
              </span>

              <button
                onClick={handleSave}
                className="px-4 py-[6px] rounded-pill text-sm font-medium text-sf-green bg-transparent border border-[rgba(62,207,142,0.3)]"
              >
                Save
              </button>
            </div>

            <textarea
              className="flex-1 bg-sf-bg p-4 font-mono text-[13px] leading-[1.7] text-sf-text outline-none resize-none"
              spellCheck={false}
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <span className="text-sm text-sf-text-muted">
              ← Select a rule file
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-3 p-3">
      {[...Array(6)].map((_, i) => (
        <div
          key={i}
          className="h-10 rounded bg-sf-surface animate-pulse"
        />
      ))}
    </div>
  );
}