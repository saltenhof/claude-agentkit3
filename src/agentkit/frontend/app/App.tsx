import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactElement } from 'react';

import { ApiClient, ApiError } from './api';
import { Shell } from './app_shell/layout/Shell';
import { viewModeFromHash, type ViewMode } from './app_shell/routing/viewMode';
import type { DependencyEdge, ExecutionInputSnapshot, ExecutionLimits } from './contexts/execution_planning/types';
import type { HubSession, HubStatusSnapshot } from './contexts/multi_llm_hub/types';
import type { ProjectModeLock, ProjectSummary, StoryCounters } from './contexts/project_management/types';
import type { StoryDetail, StorySummary } from './contexts/story_context_manager/types';
import { TakeoverApprovalOverlay } from './contexts/story_context_manager/components/TakeoverApprovalOverlay';
import type {
  TakeoverApprovalRequest,
  TakeoverChallengeNotice,
} from './contexts/story_context_manager/takeoverTypes';

const CSRF_STORAGE_KEY = 'agentkit.csrf';

export interface AppData {
  projects: ProjectSummary[];
  selectedProject: ProjectSummary | null;
  stories: StorySummary[];
  counters: StoryCounters | null;
  modeLock: ProjectModeLock | null;
  dependencies: DependencyEdge[];
  executionInput: ExecutionInputSnapshot | null;
  executionLimits: ExecutionLimits | null;
  hubStatus: HubStatusSnapshot | null;
  hubSessions: HubSession[];
  hubError: string | null;
  selectedStory: StoryDetail | null;
  selectedStoryId: string | null;
  selectedTakeoverApproval: TakeoverApprovalRequest | null;
  viewMode: ViewMode;
  loading: boolean;
  offline: boolean;
  error: string | null;
}

export interface AppActions {
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  selectProject: (projectKey: string) => void;
  selectStory: (storyId: string | null) => void;
  reload: () => Promise<void>;
  approveStory: (storyId: string) => Promise<void>;
  rejectStory: (storyId: string) => Promise<void>;
  cancelStory: (storyId: string, reason: string) => Promise<void>;
  updateStoryFields: (storyId: string, updates: Record<string, unknown>) => Promise<void>;
}

export function App(): ReactElement {
  const [csrfToken, setCsrfToken] = useState<string | null>(() => sessionStorage.getItem(CSRF_STORAGE_KEY));
  const [authenticated, setAuthenticated] = useState<boolean>(csrfToken !== null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjectKey, setSelectedProjectKey] = useState<string | null>(null);
  const [stories, setStories] = useState<StorySummary[]>([]);
  const [counters, setCounters] = useState<StoryCounters | null>(null);
  const [modeLock, setModeLock] = useState<ProjectModeLock | null>(null);
  const [dependencies, setDependencies] = useState<DependencyEdge[]>([]);
  const [executionInput, setExecutionInput] = useState<ExecutionInputSnapshot | null>(null);
  const [executionLimits, setExecutionLimits] = useState<ExecutionLimits | null>(null);
  const [hubStatus, setHubStatus] = useState<HubStatusSnapshot | null>(null);
  const [hubSessions, setHubSessions] = useState<HubSession[]>([]);
  const [hubError, setHubError] = useState<string | null>(null);
  const [selectedStoryId, setSelectedStoryId] = useState<string | null>(null);
  const [selectedStory, setSelectedStory] = useState<StoryDetail | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>(() => viewModeFromHash(globalThis.location.hash));
  const [loading, setLoading] = useState<boolean>(true);
  const [offline, setOffline] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [takeoverApprovals, setTakeoverApprovals] = useState<TakeoverApprovalRequest[]>([]);
  const [takeoverChallenges, setTakeoverChallenges] = useState<TakeoverChallengeNotice[]>([]);
  const [takeoverBusy, setTakeoverBusy] = useState(false);
  const [takeoverError, setTakeoverError] = useState<string | null>(null);

  const selectedProject = projects.find((project) => project.project_key === selectedProjectKey) ?? null;
  const selectedProjectRef = useRef<ProjectSummary | null>(selectedProject);
  selectedProjectRef.current = selectedProject;

  const unauthorize = useCallback(() => {
    sessionStorage.removeItem(CSRF_STORAGE_KEY);
    setCsrfToken(null);
    setAuthenticated(false);
    setSelectedStory(null);
    setSelectedStoryId(null);
    setTakeoverApprovals([]);
    setTakeoverChallenges([]);
  }, []);

  const api = useMemo(
    () =>
      new ApiClient({
        getCsrfToken: () => sessionStorage.getItem(CSRF_STORAGE_KEY),
        onUnauthorized: unauthorize,
      }),
    [unauthorize],
  );

  const loadProjectNeutralData = useCallback(async (): Promise<void> => {
    const [hubSnapshot, sessions] = await Promise.allSettled([
      api.hubStatus(),
      api.hubSessions(),
    ]);

    if (hubSnapshot.status === 'fulfilled') {
      setHubStatus(hubSnapshot.value);
      setHubError(null);
    } else {
      setHubStatus(null);
      setHubError(errorMessage(hubSnapshot.reason, 'Hub-Status konnte nicht geladen werden.'));
    }

    if (sessions.status === 'fulfilled') {
      setHubSessions(sessions.value);
      if (hubSnapshot.status === 'fulfilled') {
        setHubError(null);
      }
    } else {
      setHubSessions([]);
      setHubError(errorMessage(sessions.reason, 'Hub-Sessions konnten nicht geladen werden.'));
    }

  }, [api]);

  const loadProjectData = useCallback(
    async (projectKey: string): Promise<void> => {
      setLoading(true);
      setError(null);
      const [storyList, storyCounters, lock, graph, input, limits] = await Promise.allSettled([
        api.stories(projectKey),
        api.counters(projectKey),
        api.modeLock(projectKey),
        api.dependencyGraph(projectKey),
        api.executionInput(projectKey),
        api.executionLimits(projectKey),
      ]);
      if (storyList.status === 'fulfilled') {
        setStories(storyList.value);
      }
      if (storyCounters.status === 'fulfilled' && storyCounters.value !== undefined) {
        setCounters(storyCounters.value);
      }
      if (lock.status === 'fulfilled' && lock.value !== undefined) {
        setModeLock(lock.value);
      }
      if (graph.status === 'fulfilled') {
        setDependencies(graph.value);
      }
      if (input.status === 'fulfilled' && input.value !== undefined) {
        setExecutionInput(input.value);
      }
      if (limits.status === 'fulfilled' && limits.value !== undefined) {
        setExecutionLimits(limits.value);
      }
      if (storyList.status === 'rejected') {
        setError('Stories konnten nicht geladen werden.');
        setOffline(true);
      } else {
        setError(null);
        setOffline(false);
      }
      setLoading(false);
    },
    [api],
  );

  const loadProjects = useCallback(async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const loadedProjects = await api.projects();
      const currentKey = selectedProjectRef.current?.project_key;
      const nextProject =
        loadedProjects.find((project) => project.project_key === currentKey) ??
        loadedProjects.find((project) => project.status === 'active') ??
        loadedProjects[0] ??
        null;
      setProjects(loadedProjects);
      setSelectedProjectKey(nextProject?.project_key ?? null);
      setAuthenticated(true);
      setOffline(false);
      await loadProjectNeutralData();
      if (nextProject !== null) {
        await loadProjectData(nextProject.project_key);
      }
    } catch (err) {
      handleError(err, setError, setOffline);
    } finally {
      setLoading(false);
    }
  }, [api, loadProjectData, loadProjectNeutralData]);

  const loadTakeoverApprovals = useCallback(async (): Promise<void> => {
    try {
      const response = await api.takeoverApprovals();
      setTakeoverApprovals(response.approvals);
      setTakeoverChallenges(response.challenges);
      setTakeoverError(null);
    } catch (err) {
      setTakeoverError(errorMessage(err, 'Takeover-Freigaben konnten nicht geladen werden.'));
    }
  }, [api]);

  useEffect(() => {
    const onHashChange = (): void => {
      setViewMode(viewModeFromHash(globalThis.location.hash));
    };
    globalThis.addEventListener('hashchange', onHashChange);
    return () => globalThis.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    loadProjects().catch((err: unknown) => handleError(err, setError, setOffline));
  }, [loadProjects]);

  useEffect(() => {
    if (!authenticated || selectedProjectKey === null) {
      return undefined;
    }
    let closed = false;
    const source = new EventSource(
      `/v1/projects/${encodeURIComponent(selectedProjectKey)}/events?topics=stories,phases,planning,telemetry,coverage`,
      { withCredentials: true },
    );
    source.onmessage = () => {
      if (!closed) {
        loadProjectData(selectedProjectKey).catch((err: unknown) => {
          if (!closed) {
            handleError(err, setError, setOffline);
          }
        });
      }
    };
    source.onerror = () => {
      setOffline(true);
    };
    source.onopen = () => {
      if (!closed) {
        setOffline(false);
        loadProjectData(selectedProjectKey).catch((err: unknown) => {
          if (!closed) {
            handleError(err, setError, setOffline);
          }
        });
      }
    };
    return () => {
      closed = true;
      source.close();
    };
  }, [authenticated, loadProjectData, selectedProjectKey]);

  useEffect(() => {
    if (selectedProjectKey === null || selectedStoryId === null) {
      setSelectedStory(null);
      return;
    }
    let ignore = false;
    api
      .story(selectedProjectKey, selectedStoryId)
      .then((story) => {
        if (!ignore) {
          setSelectedStory(story);
        }
      })
      .catch((err: unknown) => {
        if (!ignore) {
          if (err instanceof ApiError && err.status === 404) {
            setSelectedStoryId(null);
            setSelectedStory(null);
            setError('Story wurde entfernt.');
            return;
          }
          handleError(err, setError, setOffline);
        }
      });
    return () => {
      ignore = true;
    };
  }, [api, selectedProjectKey, selectedStoryId]);

  useEffect(() => {
    if (!authenticated) {
      return undefined;
    }
    let closed = false;
    const source = new EventSource('/v1/events/governance?topics=governance', {
      withCredentials: true,
    });
    const resync = (): void => {
      if (!closed) {
        loadTakeoverApprovals().catch(() => undefined);
      }
    };
    const onGovernanceEvent = (event: MessageEvent<string>): void => {
      try {
        const payload = JSON.parse(event.data) as { event_type?: string };
        if (payload.event_type === 'takeover_approval_changed' || payload.event_type === 'pending_takeover_approval') {
          resync();
        }
      } catch {
        setTakeoverError('Ungültiges Governance-Event – Freigabe bleibt fail-closed.');
      }
    };
    source.onmessage = onGovernanceEvent;
    source.addEventListener('governance', onGovernanceEvent);
    source.onopen = resync;
    source.onerror = () => {
      setTakeoverError('Governance-Stream getrennt – Re-Sync beim Wiederverbinden ausstehend.');
    };
    return () => {
      closed = true;
      source.removeEventListener('governance', onGovernanceEvent);
      source.close();
    };
  }, [authenticated, loadTakeoverApprovals]);

  const confirmTakeover = useCallback(async (approval: TakeoverApprovalRequest): Promise<void> => {
    setTakeoverBusy(true);
    setTakeoverError(null);
    try {
      const result = await api.confirmStoryRunTakeover(approval);
      if (result.status === 'rejected') {
        throw new ApiError('Takeover-Challenge wurde abgewiesen.', 409, result.error_code ?? 'conflict');
      }
      await loadTakeoverApprovals();
    } catch (err) {
      setTakeoverError(errorMessage(err, 'Takeover konnte nicht bestätigt werden.'));
      await loadTakeoverApprovals();
    } finally {
      setTakeoverBusy(false);
    }
  }, [api, loadTakeoverApprovals]);

  const denyTakeover = useCallback(async (approval: TakeoverApprovalRequest): Promise<void> => {
    setTakeoverBusy(true);
    setTakeoverError(null);
    try {
      await api.denyStoryRunTakeover(approval, 'Denied from AgentKit UI');
      await loadTakeoverApprovals();
    } catch (err) {
      setTakeoverError(errorMessage(err, 'Takeover konnte nicht abgelehnt werden.'));
    } finally {
      setTakeoverBusy(false);
    }
  }, [api, loadTakeoverApprovals]);

  const actions: AppActions = useMemo(
    () => ({
      login: async (username: string, password: string) => {
        setError(null);
        const result = await api.login(username, password);
        sessionStorage.setItem(CSRF_STORAGE_KEY, result.csrf_token);
        setCsrfToken(result.csrf_token);
        setAuthenticated(true);
        await loadProjects();
      },
      logout: async () => {
        try {
          await api.logout();
        } finally {
          unauthorize();
          setProjects([]);
          setStories([]);
          setCounters(null);
          setModeLock(null);
          setHubStatus(null);
          setHubSessions([]);
          setTakeoverApprovals([]);
          setTakeoverChallenges([]);
        }
      },
      selectProject: (projectKey: string) => {
        setSelectedProjectKey(projectKey);
        setSelectedStoryId(null);
        setSelectedStory(null);
        loadProjectData(projectKey).catch((err: unknown) => handleError(err, setError, setOffline));
      },
      selectStory: (storyId: string | null) => {
        setSelectedStoryId(storyId);
      },
      reload: loadProjects,
      approveStory: async (storyId: string) => {
        if (selectedProjectKey === null) {
          return;
        }
        await api.approveStory(selectedProjectKey, storyId);
        await loadProjectData(selectedProjectKey);
      },
      rejectStory: async (storyId: string) => {
        if (selectedProjectKey === null) {
          return;
        }
        await api.rejectStory(selectedProjectKey, storyId);
        await loadProjectData(selectedProjectKey);
      },
      cancelStory: async (storyId: string, reason: string) => {
        if (selectedProjectKey === null) {
          return;
        }
        await api.cancelStory(selectedProjectKey, storyId, reason);
        await loadProjectData(selectedProjectKey);
      },
      updateStoryFields: async (storyId: string, updates: Record<string, unknown>) => {
        if (selectedProjectKey === null) {
          return;
        }
        await api.updateStoryFields(selectedProjectKey, storyId, updates);
        await loadProjectData(selectedProjectKey);
      },
    }),
    [api, loadProjectData, loadProjects, selectedProjectKey, unauthorize],
  );

  const data: AppData = {
    projects,
    selectedProject,
    stories,
    counters,
    modeLock,
    dependencies,
    executionInput,
    executionLimits,
    hubStatus,
    hubSessions,
    hubError,
    selectedStory,
    selectedStoryId,
    selectedTakeoverApproval:
      takeoverApprovals.find((approval) => approval.story_id === selectedStoryId) ?? null,
    viewMode,
    loading,
    offline,
    error,
  };

  const overlayApproval = takeoverApprovals[0] ?? null;
  const overlayChallenge = overlayApproval === null
    ? null
    : takeoverChallenges.find((challenge) => challenge.challenge_id === overlayApproval.challenge_id) ?? null;

  return (
    <Shell
      actions={actions}
      authenticated={authenticated || csrfToken !== null}
      data={data}
      overlay={overlayApproval === null ? null : (
        <TakeoverApprovalOverlay
          approval={overlayApproval}
          busy={takeoverBusy}
          challenge={overlayChallenge}
          error={takeoverError}
          onConfirm={confirmTakeover}
          onDeny={denyTakeover}
        />
      )}
    />
  );
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    return `${err.errorCode}: ${err.message}`;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return fallback;
}

function handleError(
  err: unknown,
  setError: (value: string | null) => void,
  setOffline: (value: boolean) => void,
): void {
  if (err instanceof ApiError) {
    if (err.status === 401) {
      setError(null);
      return;
    }
    setError(`${err.errorCode}: ${err.message}`);
    setOffline(err.status === 0 || err.status >= 502);
    return;
  }
  if (err instanceof TypeError) {
    setError('Backend nicht erreichbar.');
    setOffline(true);
    return;
  }
  setError('Unerwarteter Fehler.');
}
