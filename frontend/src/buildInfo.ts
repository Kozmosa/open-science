export interface DeploymentBuildInfo {
  shortCommit: string | null;
  committedAt: string | null;
}

declare const __AINRF_BUILD_INFO__:
  | DeploymentBuildInfo
  | undefined;

export const deploymentBuildInfo: DeploymentBuildInfo =
  typeof __AINRF_BUILD_INFO__ === 'object' && __AINRF_BUILD_INFO__ !== null
    ? __AINRF_BUILD_INFO__
    : {
        shortCommit: null,
        committedAt: null,
      };
