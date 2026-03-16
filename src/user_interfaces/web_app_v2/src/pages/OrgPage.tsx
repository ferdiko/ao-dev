import { useNavigate } from "react-router-dom";
import { Breadcrumb } from "../components/Breadcrumb";
import { mockProjects } from "../data/mock";
import { Play, Users, Calendar, Clock } from "lucide-react";

export function OrgPage() {
  const navigate = useNavigate();

  return (
    <div className="project-page">
      <Breadcrumb items={[{ label: "Organization" }]} />
      <div className="org-page">
        <div className="org-header">
          <div>
            <h1 className="org-title">Projects</h1>
            <p className="org-subtitle">
              {mockProjects.length} projects in Sovara Labs
            </p>
          </div>
          <button className="btn btn-primary">+ New Project</button>
        </div>

        <div className="project-grid">
          {mockProjects.map((project) => (
            <div
              key={project.id}
              className="project-card"
              onClick={() => navigate(`/project/${project.id}`)}
            >
              <div className="project-card-name">{project.name}</div>
              <div className="project-card-desc">{project.description}</div>
              <div className="project-card-meta">
                <div className="project-card-meta-item">
                  <Play size={12} />
                  <span className="project-card-meta-value">
                    {project.numRuns}
                  </span>{" "}
                  runs
                </div>
                <div className="project-card-meta-item">
                  <Users size={12} />
                  <span className="project-card-meta-value">
                    {project.numUsers}
                  </span>{" "}
                  users
                </div>
                <div className="project-card-meta-item">
                  <Calendar size={12} />
                  {project.createdAt}
                </div>
                <div className="project-card-meta-item">
                  <Clock size={12} />
                  {project.lastModified}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
