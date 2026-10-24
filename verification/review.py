"""
What manual reviewers check, and the reasons they can give for a rejection.
Kept in code (not the database) so the admin UI, the API and the creator's
notification always agree. Keys are stored; labels and messages can change.
"""

# Every item must be ticked to approve.
CHECKLIST = [
    ('name_matches', 'The name on the ID matches the name on the account'),
    ('face_matches', 'The face in the selfie matches the photo on the ID'),
    ('holding_id', 'The selfie shows the person holding this ID next to their face'),
    ('id_valid', 'The ID is not expired'),
    ('readable', 'The ID is clear and fully visible'),
    ('not_edited', 'Nothing looks edited, printed from a screen, or photocopied'),
]
CHECKLIST_KEYS = [key for key, _ in CHECKLIST]

# key -> (label for admins, message for the creator)
REJECTION_REASONS = {
    'name_mismatch': ('Name does not match the account',
                      'The name on your ID does not match the name on your account. '
                      'Update your profile name or use an ID in your name.'),
    'face_mismatch': ('Face does not match the ID',
                      'We could not match your selfie to the photo on your ID. '
                      'Take a clear, well-lit selfie facing the camera.'),
    'not_holding_id': ('Selfie does not show the ID',
                       'Your selfie must show you holding the same ID next to your face.'),
    'id_expired': ('ID is expired', 'Your ID has expired. Please use a valid ID.'),
    'unreadable': ('ID is blurry, cropped or unreadable',
                   'Your ID photo was not clear enough. Make sure the whole ID is visible, '
                   'in focus and without glare.'),
    'suspected_tampering': ('ID looks edited, printed or photocopied',
                            'We could not accept the ID you provided. Please photograph your '
                            'original physical ID.'),
    'unsupported_document': ('Not an accepted type of ID',
                             'Please use a national ID card, driver\'s licence, international '
                             'passport, voter\'s card or residence permit.'),
    'other': ('Other (explain in the note)',
              'Your verification was not approved. See the note from our team.'),
}


def options():
    """For the admin UI."""
    return {
        'checklist': [{'key': key, 'label': label} for key, label in CHECKLIST],
        'rejection_reasons': [{'key': key, 'label': label}
                              for key, (label, _) in REJECTION_REASONS.items()],
    }


def creator_message(reason, note=None):
    message = REJECTION_REASONS.get(reason, REJECTION_REASONS['other'])[1]
    if reason == 'other' and note:
        message = f'Your verification was not approved: {note}'
    return message
