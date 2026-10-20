/* State shared between modules: the open transcript and the upload in progress. */
export const state = {
  file: null,      // file chosen in the upload dialog
  jobId: null,     // id of the running job, then of the open transcript
  duration: 0,
  busy: false,     // upload / transcription in progress
  turns: [],       // parsed transcript replies
  names: {},       // speaker label -> name typed by the user
  meta: null,      // meta.json of the open transcript
};
