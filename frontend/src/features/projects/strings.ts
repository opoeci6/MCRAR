/** Text of the projects feature (the add-to-project menu). The Projects page has its own file. */
export const projectsFeatureStrings = {
  addToProject: 'Add to project',
  menuLabel: 'Add to project',
  newProject: 'New project…',
  projectName: 'Project name',
  create: 'Create and add',
  noProjects: 'No projects yet. Create the first one below.',
  tracks: (count: number) => `${count} ${count === 1 ? 'track' : 'tracks'}`,
  added: (track: string, project: string) => `Added "${track}" to ${project}`,
  createdAndAdded: (track: string, project: string) => `Created ${project} and added "${track}"`,
  removed: (track: string, project: string) => `Removed "${track}" from ${project}`,
  untitled: 'Untitled',
  hasTrack: 'On the shortlist. Select to remove it.',
  confirmation: (project: string) => `Added to ${project}`,
  openProject: 'Open project',
  done: 'Done',
}
