import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { plannerApi } from "../../api/planner";
import { ApiErrorNotice } from "../../components/shared/api-error-notice";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/form";
import { CenteredModal } from "../../components/ui/centered-modal";

export interface EditableGroup {
  id: string;
  name: string;
  color: string;
  version: number;
}

export function GroupManager({
  groups,
  open,
  onClose,
}: {
  groups: EditableGroup[];
  open: boolean;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [color, setColor] = useState("#1769e0");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [colors, setColors] = useState<Record<string, string>>({});
  const [deleteItems, setDeleteItems] = useState<Record<string, boolean>>({});
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: ["planner"] });
  const create = useMutation({
    mutationFn: () => {
      if (!name.trim()) throw new Error("日程组名称不能为空。");
      return plannerApi.createGroup({ name: name.trim(), color });
    },
    onSuccess: async () => {
      setName("");
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (group: EditableGroup) =>
      plannerApi.deleteGroup(
        group.id,
        group.version,
        deleteItems[group.id] ?? false,
      ),
    onSuccess: refresh,
  });
  const rename = useMutation({
    mutationFn: (group: EditableGroup) => {
      const nextName = (drafts[group.id] ?? group.name).trim();
      if (!nextName) throw new Error("日程组名称不能为空。");
      return plannerApi.patchGroup(
        group.id,
        { name: nextName, color: colors[group.id] ?? group.color },
        group.version,
      );
    },
    onSuccess: refresh,
  });
  return (
    <CenteredModal
      onOpenChange={(next) => !next && onClose()}
      open={open}
      title="管理个人日程组"
      size="lg"
    >
      <form
        className="mt-4 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <Input
          onChange={(event) => setName(event.target.value)}
          placeholder="新日程组名称"
          value={name}
        />
        <Input
          aria-label="日程组颜色"
          onChange={(event) => setColor(event.target.value)}
          type="color"
          value={color}
        />
        <Button disabled={create.isPending} type="submit" variant="primary">
          创建
        </Button>
      </form>
      {create.error || remove.error || rename.error ? (
        <ApiErrorNotice error={create.error ?? remove.error ?? rename.error} />
      ) : null}
      <ul className="mt-4 space-y-2">
        {groups.map((group) => (
          <li className="planner-filters" key={group.id}>
            <span
              className="h-4 w-4 rounded-full"
              style={{ background: group.color }}
            />
            <Input
              aria-label={`${group.name} 的名称`}
              className="flex-1"
              onChange={(event) =>
                setDrafts((current) => ({
                  ...current,
                  [group.id]: event.target.value,
                }))
              }
              value={drafts[group.id] ?? group.name}
            />
            <Input
              aria-label={`${group.name} 的颜色`}
              onChange={(event) =>
                setColors((current) => ({
                  ...current,
                  [group.id]: event.target.value,
                }))
              }
              type="color"
              value={colors[group.id] ?? group.color}
            />
            <Button
              disabled={rename.isPending || remove.isPending}
              onClick={() => rename.mutate(group)}
            >
              保存
            </Button>
            <label className="text-xs">
              <input
                checked={deleteItems[group.id] ?? false}
                onChange={(event) =>
                  setDeleteItems((current) => ({
                    ...current,
                    [group.id]: event.target.checked,
                  }))
                }
                type="checkbox"
              />{" "}
              同时删除组内项目
            </label>
            <Button
              disabled={rename.isPending || remove.isPending}
              onClick={() => remove.mutate(group)}
              variant="danger"
            >
              删除
            </Button>
          </li>
        ))}
      </ul>
    </CenteredModal>
  );
}
