#!/usr/bin/env python3

"""The primary entry point for Cook's custom executor.
This module configures logging and starts the executor's driver thread.
"""

import faulthandler
import logging
import os
import requests
import signal
import sys

import cook.sidecar.config as csc
import cook.sidecar.tracker as cst
from cook.sidecar.version import __version__


def start_progress_trackers():
    try:
        config = csc.initialize_config(os.environ)

        default_url = config.callback_url
        current_url = default_url

        def send_progress_message(message):
            nonlocal current_url
            try:
                for i in range(config.max_post_redirect_follow + 1):
                    response = requests.post(current_url, allow_redirects=False, json=message)
                    if response.status_code == 202:
                        return True
                    elif response.is_redirect and response.status_code == 307:
                        current_url = response.headers['location']
                        logging.info(f'Redirected! Changed progress update callback url to: {current_url}')
                    else:
                        logging.warning(f'Unexpected progress update response ({response.status_code}): {response.content}')
                        break
                else:
                    logging.warning(f'Reached max redirect retries ({config.max_post_redirect_follow})')
            except Exception:
                logging.exception(f'Error raised while posting progress update to {current_url}')
            current_url = default_url
            logging.info(f'Failed to post progress update. Reset progress update callback url: {current_url}')
            return False

        max_message_length = config.max_message_length
        sample_interval_ms = config.progress_sample_interval_ms
        sequence_counter = cst.ProgressSequenceCounter()
        progress_updater = cst.ProgressUpdater(max_message_length, sample_interval_ms, send_progress_message)

        def launch_progress_tracker(progress_location, location_tag):
            logging.info(f'Location {progress_location} tagged as [tag={location_tag}]')
            progress_tracker = cst.ProgressTracker(config, sequence_counter, progress_updater, progress_location, location_tag)
            progress_tracker.start()
            return progress_tracker

        progress_locations = {config.progress_output_name: 'progress',
                              config.stderr_file(): 'stderr',
                              config.stdout_file(): 'stdout'}
        logging.info(f'Progress will be tracked from {len(progress_locations)} locations')
        progress_trackers = [launch_progress_tracker(file, name) for file, name in progress_locations.items()]

        def handle_interrupt(interrupt_code, _):
            msg = f'Progress Reporter interrupted with code {interrupt_code}'
            logging.info(msg)
            # force send the latest progress state if available
            for progress_tracker in progress_trackers:
                progress_tracker.force_send_progress_update()
            sys.exit(msg)

        signal.signal(signal.SIGINT, handle_interrupt)
        signal.signal(signal.SIGTERM, handle_interrupt)

        def dump_traceback(signal, frame):
            faulthandler.dump_traceback()

        signal.signal(signal.SIGUSR1, dump_traceback)

        return progress_trackers

    except Exception:
        logging.exception('Error starting Progress Reporter')
        return None


def main(args=None):
    logging.info(f'Starting cook.sidecar {__version__} progress reporter')
    if len(sys.argv) == 2 and sys.argv[1] == "--version":
        print(__version__)
    else:
        log_level = os.environ.get('SIDECAR_LOG_LEVEL', 'INFO')
        logging.basicConfig(level = log_level,
                            stream = sys.stderr,
                            format='%(asctime)s %(levelname)s %(message)s')
        progress_trackers = start_progress_trackers()
        if progress_trackers is None:
            sys.exit('Failed to start progress trackers')
        # wait for all background threads to exit
        # (but this process will probably be killed first instead)
        for progress_tracker in progress_trackers:
            progress_tracker.join()


if __name__ == '__main__':
    main()
