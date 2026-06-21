import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactElement } from 'react';

import { ApiClient, ApiError } from './api';
import { Shell } from './app_shell/layout/Shell';
import { viewModeFromHash, type ViewMode } from './app_shell/routing/viewMode';
import type { DependencyEdge, ExecutionInputSnapshot, ExecutionLimits } from './contexts/execution_planning/types';
import type { ProjectModeLock, ProjectSummary, StoryCounters } from './contexts/project_management/types';
import type { StoryDetail, StorySummary } from './contexts/story_context_manager/types';

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
  selectedStory: StoryDetail | null;
  selectedStoryId: string | null;
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
  const [selectedStoryId, setSelectedStoryId] = useState<string | null>(null);
  const [selectedStory, setSelectedStory] = useState<StoryDetail | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>(() => viewModeFromHash(window.location.hash));
  const [loading, setLoading] = useState<boolean>(true);
  const [offline, setOffline] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const selectedProject = projects.find((project) => project.project_key === selectedProjectKey) ?? null;
  const selectedProjectRef = useRef<ProjectSummary | null>(selectedProject);
  selectedProjectRef.current = selectedProject;

  const unauthorize = useCallback(() => {
    sessionStorage.removeItem(CSRF_STORAGE_KEY);
    setCsrfToken(null);
    setAuthenticated(false);
    setSelectedStory(null);
    setSelectedStoryId(null);
  }, []);

  const api = useMemo(
    () =>
      new ApiClient({
        getCsrfToken: () => sessionStorage.getItem(CSRF_STORAGE_KEY),
        onUnauthorized: unauthorize,
      }),
    [unauthorize],
  );

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
      const failures = [storyList, storyCounters, lock, graph, input, limits].filter(
        (result) => result.status === 'rejected',
      );
      if (failures.length > 0) {
        setError(`${failures.length} Backend-Teilflaeche(n) nicht geladen.`);
        setOffline(true);
      } else {
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
      if (nextProject !== null) {
        await loadProjectData(nextProject.project_key);
      }
    } catch (err) {
      handleError(err, setError, setOffline);
    } finally {
      setLoading(false);
    }
  }, [api, loadProjectData]);

  useEffect(() => {
    const onHashChange = (): void => {
      setViewMode(viewModeFromHash(window.location.hash));
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    void loadProjects();
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
        void loadProjectData(selectedProjectKey);
      }
    };
    source.onerror = () => {
      setOffline(true);
    };
    source.onopen = () => {
      if (!closed) {
        setOffline(false);
        void loadProjectData(selectedProjectKey);
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
        }
      },
      selectProject: (projectKey: string) => {
        setSelectedProjectKey(projectKey);
        setSelectedStoryId(null);
        setSelectedStory(null);
        void loadProjectData(projectKey);
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
    selectedStory,
    selectedStoryId,
    viewMode,
    loading,
    offline,
    error,
  };

  return (
    <Shell
      actions={actions}
      authenticated={authenticated || csrfToken !== null}
      data={data}
    />
  );
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
