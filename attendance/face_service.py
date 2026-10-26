import cv2
import numpy as np
from os import PathLike
from threading import Lock
from insightface.app import FaceAnalysis
from django.conf import settings
from .models import StudentFace

_face_app = None
_face_app_lock = Lock()


def _get_face_app():
    """Load the recognition model only when a face operation is requested."""
    global _face_app

    if _face_app is None:
        with _face_app_lock:
            if _face_app is None:
                model_root = settings.BASE_DIR / ".face_models"
                _face_app = FaceAnalysis(
                    name="buffalo_l",
                    root=str(model_root),
                    providers=["CPUExecutionProvider"],
                )
                _face_app.prepare(ctx_id=-1, det_size=(640, 640))

    return _face_app


def get_face_embeddings_from_image(image):
    """Return one embedding per detected face in the image."""
    if isinstance(image, (str, PathLike)):
        img = cv2.imread(str(image))
    else:
        img = image

    if img is None:
        return []

    faces = _get_face_app().get(img)
    return [face.embedding for face in faces]


def estimate_face_pose(image):
    """Estimate coarse yaw and pitch angles for live enrollment guidance."""
    if isinstance(image, (str, PathLike)):
        img = cv2.imread(str(image))
    else:
        img = image
    if img is None:
        return None

    faces = _get_face_app().get(img)
    if not faces:
        return None

    face = max(faces, key=lambda item: (item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1]))
    if face.kps is None or len(face.kps) < 5:
        return None

    height, width = img.shape[:2]
    image_points = np.asarray(face.kps[:5], dtype=np.float64)
    model_points = np.asarray([
        [-225.0, 170.0, -135.0],  # left eye
        [225.0, 170.0, -135.0],   # right eye
        [0.0, 0.0, 0.0],          # nose
        [-150.0, -150.0, -125.0], # left mouth corner
        [150.0, -150.0, -125.0],  # right mouth corner
    ], dtype=np.float64)
    focal_length = float(width)
    camera_matrix = np.asarray([
        [focal_length, 0.0, width / 2.0],
        [0.0, focal_length, height / 2.0],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)

    success, rotation_vector, _ = cv2.solvePnP(
        model_points,
        image_points,
        camera_matrix,
        np.zeros((4, 1), dtype=np.float64),
        flags=cv2.SOLVEPNP_EPNP,
    )
    if not success:
        return None

    rotation_matrix, _ = cv2.Rodrigues(rotation_vector)
    euler_angles = cv2.RQDecomp3x3(rotation_matrix)[0]
    return {
        "pitch": float(euler_angles[0]),
        "yaw": float(euler_angles[1]),
        "face_count": len(faces),
    }


def get_embedding_from_image(image):
    """Return the largest face embedding, for single-student registration."""
    if isinstance(image, (str, PathLike)):
        img = cv2.imread(str(image))
    else:
        img = image
    if img is None:
        return None

    faces = _get_face_app().get(img)
    if not faces:
        return None
    face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return face.embedding


def register_student_face(student, image_paths: list, required_image_paths=None):
    embeddings = []
    required_image_paths = {str(path) for path in (required_image_paths or [])}
    detected_live_frames = 0

    for path in image_paths:
        emb = get_embedding_from_image(path)
        if emb is not None:
            embeddings.append(emb.tolist())
            if str(path) in required_image_paths:
                detected_live_frames += 1
        elif str(path) in required_image_paths:
            return False, "A live camera frame did not contain a clear face. Retake the frames and try again."

    if detected_live_frames < 3:
        return False, "At least three clear live camera frames are required. No face profile was saved."

    if not embeddings:
        return False, "No face detected in uploaded photos."

    StudentFace.objects.update_or_create(
        student=student,
        defaults={
            "embeddings": embeddings,
            "is_active": True,
        },
    )
    return True, f"Successfully registered with {len(embeddings)} face(s)."


def recognize_faces(image, threshold=None):
    """Match every detected face, returning unique students and face count."""
    if threshold is None:
        threshold = getattr(settings, "FACE_RECOGNITION_THRESHOLD", 0.42)

    query_embeddings = get_face_embeddings_from_image(image)
    if not query_embeddings:
        return [], 0

    profiles = StudentFace.objects.filter(is_active=True).select_related("student")
    reference_vectors = []
    reference_students = []

    for profile in profiles:
        for embedding in profile.embeddings:
            vector = np.asarray(embedding, dtype=np.float32)
            if vector.ndim != 1:
                continue
            norm = np.linalg.norm(vector)
            if norm == 0:
                continue
            reference_vectors.append(vector)
            reference_students.append(profile.student)

    if not reference_vectors:
        return [], len(query_embeddings)

    reference_matrix = np.stack(reference_vectors)
    reference_norms = np.linalg.norm(reference_matrix, axis=1)
    candidates = []

    for face_index, query_embedding in enumerate(query_embeddings):
        query = np.asarray(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query.ndim != 1 or query_norm == 0 or query.shape[0] != reference_matrix.shape[1]:
            continue

        scores = (reference_matrix @ query) / (reference_norms * query_norm)
        best_by_student = {}
        for reference_index, score in enumerate(scores):
            student = reference_students[reference_index]
            score = float(score)
            previous = best_by_student.get(student.pk)
            if previous is None or score > previous[0]:
                best_by_student[student.pk] = (score, student)

        for score, student in best_by_student.values():
            if score >= threshold:
                candidates.append((score, face_index, student))

    # Assign each detected face to at most one student and vice versa.
    matches = []
    used_faces = set()
    used_students = set()
    for score, face_index, student in sorted(candidates, reverse=True, key=lambda item: item[0]):
        if face_index in used_faces or student.pk in used_students:
            continue
        used_faces.add(face_index)
        used_students.add(student.pk)
        matches.append((student, float(score)))

    return matches, len(query_embeddings)


def recognize_face(image, threshold=None):
    """Backwards-compatible single-face match used by the webcam stream."""
    matches, _ = recognize_faces(image, threshold=threshold)
    return matches[0] if matches else (None, 0.0)
