export function createElement(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) {
    element.className = className;
  }
  if (text !== undefined) {
    element.textContent = text;
  }
  return element;
}

export function clearChildren(element) {
  element.replaceChildren();
}

export function setOptionalText(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = value ?? "-";
  }
}

export function truncateText(text, maxLength = 80) {
  const value = String(text || "");
  return value.length > maxLength ? value.slice(0, maxLength) + "..." : value;
}

export function setBusyButton(button, text = "处理中...") {
  if (!button) {
    return () => {};
  }
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = text;
  return () => {
    button.disabled = false;
    button.textContent = originalText;
  };
}

export function formatErrorDetail(detail) {
  if (typeof detail === "string") {
    return detail;
  }
  if (detail === undefined || detail === null) {
    return "";
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

export function appendConfigLine(box, label, value) {
  const line = document.createElement("div");
  line.className = "config-line";

  const name = document.createElement("b");
  name.textContent = `${label}:`;

  line.append(name, ` ${value ?? ""}`);
  box.appendChild(line);
}
